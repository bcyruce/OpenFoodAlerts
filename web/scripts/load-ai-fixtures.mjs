// Loads hand-written AI classifications (web/e2e/fixtures/ai/*.json) into DATABASE_URL for
// the smoke tests, after `ofa load-fixtures` and `ofa classify --model fake` (make
// web-fixtures). Idempotent and deterministic: fixed created_at, input_hash from the
// content, ON CONFLICT DO NOTHING; derived child rows are written with a new row only, as
// the pipeline does. "approve" marks the current row of a task approved (as ticket 20's
// review page: reviewed_value = the model's value).
//
//   DATABASE_URL=postgres://ofa:ofa@localhost:5432/ofa node scripts/load-ai-fixtures.mjs FILE...
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import postgres from "postgres";

const CREATED_AT = "2026-10-25T06:00:00Z";
const url = process.env.DATABASE_URL;
if (!url) throw new Error("DATABASE_URL is not set");
const sql = postgres(url, { max: 1, onnotice: () => {} });

async function notificationId(tx, source, key) {
  const [row] = await tx`
    SELECT n.id FROM notifications n JOIN sources s ON s.id = n.source_id
    WHERE s.code = ${source} AND n.source_key = ${key}`;
  if (!row) throw new Error(`no Notification ${source} ${key}: load the source fixtures first`);
  return row.id;
}

async function load(tx, c) {
  const id = await notificationId(tx, c.source, c.key);
  const hash = createHash("sha256")
    .update(JSON.stringify([c.source, c.key, c.task, c.value]))
    .digest("hex");
  const abstained = c.abstained ?? false;
  const [row] = await tx`
    INSERT INTO ai_classifications (notification_id, task, value, confidence, abstained,
      evidence_span, model, prompt_version, schema_version, taxonomy_version, input_hash,
      created_at)
    VALUES (${id}, ${c.task}, ${tx.json(c.value)}, ${abstained ? null : (c.confidence ?? "high")},
      ${abstained}, ${c.evidenceSpan ?? null}, 'fixture', 'v1', '1', NULL, ${hash}, ${CREATED_AT})
    ON CONFLICT DO NOTHING
    RETURNING id`;
  if (!row) return 0;
  const d = c.derived ?? {};
  if (d.productCategory !== undefined) {
    await tx`
      INSERT INTO notification_product_categories
        (notification_id, position, product_category_id, provenance, ai_classification_id)
      VALUES (${id}, 0, (SELECT id FROM product_categories WHERE rasff_id = ${d.productCategory}),
              'ai', ${row.id})`;
  }
  if (d.originCountry !== undefined) {
    await tx`
      INSERT INTO notification_countries
        (notification_id, country_iso2, role, provenance, ai_classification_id)
      VALUES (${id}, ${d.originCountry}, 'origin', 'ai', ${row.id})`;
  }
  return 1;
}

async function approve(tx, a) {
  const id = await notificationId(tx, a.source, a.key);
  const result = await tx`
    UPDATE ai_classifications c SET review_status = 'approved', reviewed_value = c.value,
      reviewed_at = coalesce(c.reviewed_at, ${CREATED_AT})
    WHERE c.id = (SELECT id FROM ai_classifications
                  WHERE notification_id = ${id} AND task = ${a.task}
                  ORDER BY created_at DESC, id DESC LIMIT 1)
      AND c.review_status = 'unreviewed'`;
  return result.count;
}

try {
  for (const file of process.argv.slice(2)) {
    const data = JSON.parse(readFileSync(file, "utf8"));
    const counts = await sql.begin(async (tx) => {
      let written = 0;
      let approved = 0;
      for (const c of data.classifications ?? []) written += await load(tx, c);
      for (const a of data.approve ?? []) approved += await approve(tx, a);
      return { written, approved };
    });
    console.log(`${file}: ${counts.written} AI classifications written, ${counts.approved} approved`);
  }
} finally {
  await sql.end();
}
