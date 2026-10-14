import { readFileSync } from "node:fs";
import path from "node:path";
import { sql } from "drizzle-orm";
import { afterAll, describe, expect, it } from "vitest";
import { DATA_CARD_FILE, loadDataCard, renderDataCard, TAXONOMY_MARKER } from "./data-card";
import { REPO_ROOT } from "./repo";
import { REPO_URL } from "./site";
import { testClient, testDb } from "./test-db";

const REPO = REPO_URL;

afterAll(() => testClient.end());

describe("renderDataCard", () => {
  it("drops the title, keeps the sections and splits at the taxonomy marker", () => {
    const card = renderDataCard(
      `# OpenFoodAlerts data card\n\nIntro.\n\n## Sources\n\nText.\n\n${TAXONOMY_MARKER}\n\nAfter the table.\n`,
    );
    expect(card.before).not.toContain("<h1");
    expect(card.before).toContain("<p>Intro.</p>");
    expect(card.before).toContain('<h2 id="sources">Sources</h2>');
    expect(card.after).toBe("<p>After the table.</p>\n");
  });

  it("gives headings stable ids for links into the page", () => {
    const card = renderDataCard(`## Taxonomy v1 (draft, not frozen)\n\n### Exclusion rules & scope\n\n${TAXONOMY_MARKER}`);
    expect(card.before).toContain('<h2 id="taxonomy-v1-draft-not-frozen">');
    expect(card.before).toContain('<h3 id="exclusion-rules-scope">');
  });

  it("points repository links at the public repository and site links at the site", () => {
    const card = renderDataCard(
      [
        "[CSV](../db/seed/taxonomy/v1-draft.csv)",
        "[ADR](adr/0003-rasff-taxonomy-single-primary-hazard.md)",
        "[evaluation](https://openfoodalerts.nl/en/evaluation)",
        "[RASFF](https://webgate.ec.europa.eu/rasff-window/)",
        "[below](#fields)",
        TAXONOMY_MARKER,
      ].join("\n\n"),
    );
    expect(card.before).toContain(`href="${REPO}/blob/main/db/seed/taxonomy/v1-draft.csv"`);
    expect(card.before).toContain(
      `href="${REPO}/blob/main/docs/adr/0003-rasff-taxonomy-single-primary-hazard.md"`,
    );
    expect(card.before).toContain('href="/en/evaluation"');
    expect(card.before).toContain('href="https://webgate.ec.europa.eu/rasff-window/"');
    expect(card.before).toContain('href="#fields"');
  });

  it("wraps tables in a focusable scroll region", () => {
    const card = renderDataCard(`| a | b |\n|---|---|\n| 1 | 2 |\n\n${TAXONOMY_MARKER}`);
    expect(card.before).toMatch(/^<div class="table-scroll" tabindex="0" role="region" aria-label="Table: a, b"><table>/);
    expect(card.before.trimEnd()).toMatch(/<\/table>\n?<\/div>$/);
  });

  it("refuses a data card without the taxonomy marker", () => {
    expect(() => renderDataCard("## Sources\n")).toThrow(/taxonomy-table/);
  });
});

describe("docs/data_card.md", () => {
  it("renders and has the taxonomy marker", () => {
    const card = loadDataCard();
    expect(card.before).toContain("<h2");
    expect(card.after.length).toBeGreaterThan(0);
  });

  it("quotes every Source's licence and attribution text exactly as the sources table has them", async () => {
    const markdown = readFileSync(path.join(REPO_ROOT, DATA_CARD_FILE), "utf8");
    const sources = await testDb.execute<{ code: string; license: string; attribution_text: string }>(
      sql`SELECT code, license, attribution_text FROM sources ORDER BY id`,
    );
    expect(sources.map((s) => s.code)).toEqual(["rasff", "nvwa", "openfda"]);
    for (const s of sources) {
      expect(markdown, s.code).toContain(s.attribution_text);
      expect(markdown, s.code).toContain(s.license);
    }
  });
});
