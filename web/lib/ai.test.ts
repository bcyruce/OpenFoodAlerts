// Integration tests for the current AI classifications of Notifications, against
// TEST_DATABASE_URL (migrated and seeded by `make test-db`). Each test replaces all
// Notifications inside a rolled-back transaction; expected values are read off the rows.
import { sql } from "drizzle-orm";
import { afterAll, describe, expect, it } from "vitest";
import { getAiClassifications, getAiSummary } from "./ai";
import { testClient } from "./test-db";
import { ALLERGENS, notificationId, withNotifications, type Row } from "./test-notifications";

afterAll(() => testClient.end());

const PEANUT: Row = {
  source: "nvwa",
  key: "/actueel/nieuws/2026/10/20/veiligheidswaarschuwing-pinda",
  title: "Veiligheidswaarschuwing pinda in koekjes",
  ai: [
    {
      task: "hazard_category",
      value: { category: "foreign bodies" },
      promptVersion: "v1",
      createdAt: "2026-10-24T10:00:00Z",
    },
    {
      task: "hazard_category",
      value: { category: "allergens" },
      promptVersion: "v2",
      createdAt: "2026-10-23T10:00:00Z",
      derived: { hazardCategory: ALLERGENS },
    },
  ],
};

describe("getAiClassifications", () => {
  it("returns the result of the latest prompt version per task, with its provenance", async () => {
    await withNotifications([PEANUT], async (tx) => {
      const id = await notificationId(tx, PEANUT.key);
      const found = await getAiClassifications(tx, [id], { locale: "en" });
      expect(found.get(id)).toEqual([
        {
          task: "hazard_category",
          value: "allergens",
          label: "allergens",
          abstained: false,
          confidence: "high",
          model: "claude-haiku-5-5",
          promptVersion: "v2",
          createdAt: "2026-10-23T10:00:00.000Z",
          reviewed: false,
          classificationId: expect.any(Number),
        },
      ]);
    });
  });

  it("shows a person's corrected value instead of the model's, marked reviewed", async () => {
    const corrected: Row = {
      ...PEANUT,
      ai: [
        {
          task: "hazard_category",
          value: { category: "foreign bodies" },
          reviewStatus: "corrected",
          reviewedValue: { category: "allergens" },
        },
      ],
    };
    await withNotifications([corrected], async (tx) => {
      const id = await notificationId(tx, PEANUT.key);
      const [field] = (await getAiClassifications(tx, [id], { locale: "en" })).get(id)!;
      expect(field).toMatchObject({ value: "allergens", label: "allergens", reviewed: true });
    });
  });

  it("marks an approved value reviewed and fills in an abstained one a person corrected", async () => {
    const rows: Row = {
      ...PEANUT,
      ai: [
        { task: "hazard_category", value: { category: "allergens" }, reviewStatus: "approved" },
        {
          task: "origin_country",
          value: { country: null, abstain_reason: "model_abstained" },
          abstained: true,
          reviewStatus: "corrected",
          reviewedValue: { country: "BE" },
        },
      ],
    };
    await withNotifications([rows], async (tx) => {
      const id = await notificationId(tx, PEANUT.key);
      const fields = (await getAiClassifications(tx, [id], { locale: "nl" })).get(id)!;
      expect(fields.map((f) => [f.task, f.label, f.abstained, f.reviewed])).toEqual([
        ["hazard_category", "allergens", false, true],
        ["origin_country", "België", false, true],
      ]);
    });
  });

  it("never returns T5 or T6, orders the tasks for display and keeps abstentions", async () => {
    const all: Row = {
      ...PEANUT,
      ai: [
        { task: "product_type", value: { product_type: "food" } },
        { task: "t6_summary", value: { locale: "en", summary: "Peanuts not on the label." } },
        { task: "origin_country", value: { country: "unknown" }, evidenceSpan: null },
        { task: "product_category", value: { category: "18450" } },
        { task: "hazard", value: { hazard: "pinda" }, evidenceSpan: "pinda" },
        {
          task: "hazard_category",
          value: { category: null, abstain_reason: "model_abstained" },
          abstained: true,
        },
      ],
    };
    await withNotifications([all], async (tx) => {
      const id = await notificationId(tx, PEANUT.key);
      const fields = (await getAiClassifications(tx, [id], { locale: "en" })).get(id)!;
      expect(fields.map((f) => [f.task, f.value, f.label, f.abstained])).toEqual([
        ["hazard_category", null, null, true],
        ["hazard", "pinda", "pinda", false],
        ["product_category", "18450", "herbs and spices", false],
        ["origin_country", "unknown", "unknown", false],
      ]);
    });
  });

  it("is readable by the web role and leaves out Notifications without AI rows", async () => {
    await withNotifications([PEANUT, { ...PEANUT, key: "/other", ai: [] }], async (tx) => {
      const id = await notificationId(tx, PEANUT.key);
      const other = await notificationId(tx, "/other");
      await tx.execute(sql`SET LOCAL ROLE ofa_web`);
      const found = await getAiClassifications(tx, [id, other], { locale: "en" });
      expect([...found.keys()]).toEqual([id]);
    });
  });
});

describe("getAiSummary", () => {
  const summaries: Row = {
    ...PEANUT,
    ai: [
      {
        task: "t6_summary",
        value: { locale: "nl", summary: "Oud." },
        createdAt: "2026-10-20T10:00:00Z",
      },
      {
        task: "t6_summary",
        value: { locale: "nl", summary: "Koekjes met pinda die niet op het etiket staat." },
        createdAt: "2026-10-21T10:00:00Z",
      },
      {
        task: "t6_summary",
        value: { locale: "en", summary: "Biscuits with peanut not on the label." },
        reviewStatus: "corrected",
        reviewedValue: { locale: "en", summary: "Biscuits containing undeclared peanut." },
      },
      {
        task: "t6_summary",
        value: { locale: "zh", summary: null, abstain_reason: "model_abstained" },
        abstained: true,
      },
    ],
  };

  it("returns the newest summary in the locale, a person's correction first", async () => {
    await withNotifications([summaries], async (tx) => {
      const id = await notificationId(tx, PEANUT.key);
      expect(await getAiSummary(tx, id, "nl")).toMatchObject({
        text: "Koekjes met pinda die niet op het etiket staat.",
        reviewed: false,
        createdAt: "2026-10-21T10:00:00.000Z",
        model: "claude-haiku-5-5",
        promptVersion: "v1",
      });
      expect(await getAiSummary(tx, id, "en")).toMatchObject({
        text: "Biscuits containing undeclared peanut.",
        reviewed: true,
      });
      expect(await getAiSummary(tx, id, "zh")).toBeNull();
    });
  });
});
