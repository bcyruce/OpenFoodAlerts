import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { loadTaxonomy, TAXONOMY_DIR } from "./taxonomy";

const HEADER = "rasff_id,name_en,notifications_since_2020-01-01,label\n";

function dirWith(files: Record<string, string>): string {
  const dir = mkdtempSync(path.join(tmpdir(), "ofa-taxonomy-"));
  for (const [name, body] of Object.entries(files)) writeFileSync(path.join(dir, name), body);
  return dir;
}

describe("loadTaxonomy", () => {
  it("reads the draft and marks it as not frozen when v1.csv does not exist", () => {
    const dir = dirWith({
      "v1-draft.csv": `${HEADER}21798,allergens,535,allergens\n21788,packaging defective / incorrect,6,other\n`,
    });
    const taxonomy = loadTaxonomy(dir);
    expect(taxonomy.frozen).toBe(false);
    expect(taxonomy.file).toBe("db/seed/taxonomy/v1-draft.csv");
    expect(taxonomy.categories).toEqual([
      { rasffId: 21798, name: "allergens", count: 535, label: "allergens" },
      { rasffId: 21788, name: "packaging defective / incorrect", count: 6, label: "other" },
    ]);
  });

  it("prefers the frozen v1.csv over the draft", () => {
    const dir = dirWith({
      "v1-draft.csv": `${HEADER}21798,allergens,535,allergens\n`,
      "v1.csv": `${HEADER}21798,allergens,600,allergens\n`,
    });
    const taxonomy = loadTaxonomy(dir);
    expect(taxonomy.frozen).toBe(true);
    expect(taxonomy.file).toBe("db/seed/taxonomy/v1.csv");
    expect(taxonomy.categories[0].count).toBe(600);
  });

  it("groups the categories by label, largest first, with other last", () => {
    const dir = dirWith({
      "v1-draft.csv":
        HEADER +
        [
          "21802,biotoxins (other),0,other",
          "26580,novel food,352,GMO / novel food",
          "21798,allergens,535,allergens",
          "21788,packaging defective / incorrect,6,other",
          "26581,genetically modified,103,GMO / novel food",
          "21806,GMO / novel food,40,GMO / novel food",
        ].join("\n") +
        "\n",
    });
    const labels = loadTaxonomy(dir).labels;
    expect(labels.map((l) => [l.label, l.count, l.categories.map((c) => c.name)])).toEqual([
      ["allergens", 535, ["allergens"]],
      ["GMO / novel food", 495, ["novel food", "genetically modified", "GMO / novel food"]],
      ["other", 6, ["packaging defective / incorrect", "biotoxins (other)"]],
    ]);
  });

  it("reads quoted fields and CRLF line endings", () => {
    const dir = dirWith({
      "v1-draft.csv": `${HEADER.trimEnd()}\r\n21794,"labelling absent, incomplete",82,"labelling ""absent"""\r\n`,
    });
    expect(loadTaxonomy(dir).categories).toEqual([
      { rasffId: 21794, name: "labelling absent, incomplete", count: 82, label: 'labelling "absent"' },
    ]);
  });

  it("rejects a file without the expected columns", () => {
    const dir = dirWith({ "v1-draft.csv": "id,name\n1,x\n" });
    expect(() => loadTaxonomy(dir)).toThrow(/label/);
  });

  it("loads the repository's taxonomy: 30 RASFF categories", () => {
    const taxonomy = loadTaxonomy(TAXONOMY_DIR);
    expect(taxonomy.categories).toHaveLength(30);
    const gmo = taxonomy.labels.find((l) => l.label === "GMO / novel food");
    expect(gmo?.categories).toHaveLength(3);
    expect(taxonomy.labels.at(-1)?.label).toBe("other");
  });
});
