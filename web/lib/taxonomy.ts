/**
 * The T1 taxonomy merge table (spec §6.2): RASFF Hazard category → T1 label, read from
 * `db/seed/taxonomy/`. The frozen `v1.csv` wins; until ticket 11 freezes it, the draft
 * `v1-draft.csv` is shown and marked as not frozen. Read synchronously, so a page that
 * shows it stays static (Cache Components treat sync file reads as predictable).
 */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { REPO_ROOT } from "./repo";

export const TAXONOMY_DIR = path.join(REPO_ROOT, "db", "seed", "taxonomy");

const FROZEN = "v1.csv";
const DRAFT = "v1-draft.csv";
const COUNT_COLUMN = "notifications_since_2020-01-01";
const OTHER = "other";

export type TaxonomyCategory = {
  rasffId: number;
  /** RASFF Hazard category name. */
  name: string;
  /** RASFF Notifications since 2020-01-01 (food, feed and food contact material). */
  count: number;
  /** The T1 label the category maps to. */
  label: string;
};

export type TaxonomyLabel = {
  label: string;
  /** Sum of the member categories' counts (a Notification may count in several). */
  count: number;
  categories: TaxonomyCategory[];
};

export type Taxonomy = {
  version: 1;
  frozen: boolean;
  /** Repository path of the file that was read. */
  file: string;
  /** In file order. */
  categories: TaxonomyCategory[];
  /** Largest first; `other` last. Categories inside a label: largest first. */
  labels: TaxonomyLabel[];
};

/** RFC 4180 fields: quotes, doubled quotes inside quotes, CRLF or LF. Blank rows dropped. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') {
        quoted = false;
      } else {
        field += c;
      }
    } else if (c === '"') {
      quoted = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => r.some((f) => f.trim() !== ""));
}

export function loadTaxonomy(dir: string = TAXONOMY_DIR): Taxonomy {
  const frozen = existsSync(path.join(dir, FROZEN));
  const name = frozen ? FROZEN : DRAFT;
  const [header, ...rows] = parseCsv(readFileSync(path.join(dir, name), "utf8"));
  const wanted = ["rasff_id", "name_en", COUNT_COLUMN, "label"];
  const missing = wanted.filter((c) => !header?.includes(c));
  if (missing.length > 0) throw new Error(`${name}: missing columns ${missing.join(", ")}`);
  const [id, nameEn, count, label] = wanted.map((c) => header.indexOf(c));
  const categories = rows.map((r) => ({
    rasffId: Number(r[id]),
    name: r[nameEn],
    count: Number(r[count]),
    label: r[label],
  }));

  const byLabel = new Map<string, TaxonomyCategory[]>();
  for (const c of categories) byLabel.set(c.label, [...(byLabel.get(c.label) ?? []), c]);
  const labels = [...byLabel]
    .map(([l, members]) => ({
      label: l,
      count: members.reduce((sum, c) => sum + c.count, 0),
      categories: [...members].sort((a, b) => b.count - a.count),
    }))
    .sort((a, b) => Number(a.label === OTHER) - Number(b.label === OTHER) || b.count - a.count);

  return { version: 1, frozen, file: `db/seed/taxonomy/${name}`, categories, labels };
}
