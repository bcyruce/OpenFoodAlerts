// `/zh/jinggao` (ticket 33): NVWA food warnings with their Chinese T6 summary, newest first.
import { sql } from "drizzle-orm";
import { afterAll, describe, expect, it } from "vitest";
import { testClient, withRollback } from "./test-db";
import { withNotifications, type Row } from "./test-notifications";
import { getZhWarnings, parseZhWarningsPage } from "./zh-warnings";

afterAll(() => testClient.end());

const nvwa = (slug: string, publishedAt: string, extra: Partial<Row> = {}): Row => ({
  source: "nvwa",
  key: `/actueel/nieuws/${publishedAt.slice(0, 10).replaceAll("-", "/")}/${slug}`,
  title: `Veiligheidswaarschuwing ${slug}`,
  publishedAt,
  notificationType: "safety warning",
  ...extra,
});

const KORIANDER = nvwa("korianderzaad", "2026-10-13T07:36:00Z", {
  ai: [
    { task: "summary_zh", value: { locale: "zh", summary: "旧摘要。" }, createdAt: "2026-10-13T10:00:00Z" },
    {
      task: "summary_zh",
      value: { locale: "zh", summary: "Cook 牌磨碎芫荽籽可能含有沙门氏菌。" },
      createdAt: "2026-10-14T10:00:00Z",
      model: "claude-haiku-5-5",
      promptVersion: "v1",
    },
    { task: "summary_nl", value: { locale: "nl", summary: "Korianderzaad met Salmonella." } },
  ],
});
// Only a Dutch summary: listed without a Chinese one.
const POKEBOWL = nvwa("pokebowl", "2026-10-24T14:35:00Z", {
  ai: [{ task: "summary_nl", value: { locale: "nl", summary: "Pokebowl met allergenen." } }],
});
const CORRECTED = nvwa("oesters", "2026-06-12T12:35:00Z", {
  ai: [
    {
      task: "summary_zh",
      value: { locale: "zh", summary: "牡蛎可能含有诺如病毒。" },
      reviewStatus: "corrected",
      reviewedValue: { locale: "zh", summary: "Surasang 冷冻牡蛎可能含有诺如病毒。" },
    },
  ],
});
const ABSTAINED = nvwa("pennywafels", "2023-10-04T10:34:00Z", {
  ai: [
    {
      task: "summary_zh",
      value: { locale: "zh", summary: null, abstain_reason: "model_abstained" },
      abstained: true,
    },
  ],
});

// Not on the page: other Product types, other Sources.
const OUT_OF_SCOPE: Row[] = [
  nvwa("kinderzitje", "2026-10-20T10:00:00Z", { productType: "non-food" }),
  nvwa("hondensnack", "2026-10-21T10:00:00Z", { productType: "feed" }),
  nvwa("pepermolen", "2026-10-22T10:00:00Z", { productType: "food contact material" }),
  nvwa("onbekend", "2026-10-23T10:00:00Z", { productType: null }),
  { source: "rasff", key: "2026.9001", title: "Salmonella in sesame", publishedAt: "2026-10-25T10:00:00Z" },
  { source: "openfda", key: "H-0001-2027", title: "Peanut butter", publishedAt: "2026-10-25T10:00:00Z" },
];

describe("getZhWarnings", () => {
  it("lists NVWA food warnings newest first with their Chinese summary", async () => {
    await withNotifications([KORIANDER, POKEBOWL, CORRECTED, ABSTAINED, ...OUT_OF_SCOPE], async (tx) => {
      const found = await getZhWarnings(tx, { page: 1 });
      expect(found).toMatchObject({ page: 1, pageSize: 20, total: 4, totalPages: 1 });
      expect(found?.items.map((w) => w.title)).toEqual([
        "Veiligheidswaarschuwing pokebowl",
        "Veiligheidswaarschuwing korianderzaad",
        "Veiligheidswaarschuwing oesters",
        "Veiligheidswaarschuwing pennywafels",
      ]);
      const [pokebowl, koriander, oesters, pennywafels] = found!.items;
      expect(koriander).toMatchObject({
        sourceKey: "/actueel/nieuws/2026/10/13/korianderzaad",
        publishedAt: "2026-10-13T07:36:00.000Z",
        sourceUrl: "https://example.test//actueel/nieuws/2026/10/13/korianderzaad",
        // Detail pages exist in en and nl only (spec §9); the stream links the English one.
        detailPath: "/en/n/nvwa/actueel/nieuws/2026/10/13/korianderzaad",
        withdrawn: false,
        summary: {
          task: "summary_zh",
          locale: "zh",
          text: "Cook 牌磨碎芫荽籽可能含有沙门氏菌。",
          model: "claude-haiku-5-5",
          promptVersion: "v1",
          createdAt: "2026-10-14T10:00:00.000Z",
          reviewed: false,
        },
      });
      // No zh row, an abstention: no summary. A person's correction wins.
      expect(pokebowl.summary).toBeNull();
      expect(pennywafels.summary).toBeNull();
      expect(oesters.summary).toMatchObject({ text: "Surasang 冷冻牡蛎可能含有诺如病毒。", reviewed: true });
    });
  });

  it("pages through the warnings and has no page past the last", async () => {
    const rows = Array.from({ length: 7 }, (_, i) =>
      nvwa(`w${i + 1}`, `2026-10-${String(10 + i).padStart(2, "0")}T10:00:00Z`),
    );
    await withNotifications(rows, async (tx) => {
      const second = await getZhWarnings(tx, { page: 2, pageSize: 3 });
      expect(second).toMatchObject({ page: 2, pageSize: 3, total: 7, totalPages: 3 });
      expect(second?.items.map((w) => w.title)).toEqual([
        "Veiligheidswaarschuwing w4",
        "Veiligheidswaarschuwing w3",
        "Veiligheidswaarschuwing w2",
      ]);
      const last = await getZhWarnings(tx, { page: 3, pageSize: 3 });
      expect(last?.items.map((w) => w.title)).toEqual(["Veiligheidswaarschuwing w1"]);
      expect(await getZhWarnings(tx, { page: 4, pageSize: 3 })).toBeNull();
    });
  });

  it("has an empty first page when there are no warnings yet", async () => {
    await withNotifications([], async (tx) => {
      expect(await getZhWarnings(tx, { page: 1 })).toEqual({
        page: 1,
        pageSize: 20,
        total: 0,
        totalPages: 1,
        items: [],
      });
      expect(await getZhWarnings(tx, { page: 2 })).toBeNull();
    });
  });

  it("marks a warning NVWA withdrew", async () => {
    await withNotifications([nvwa("ingetrokken", "2026-10-01T10:00:00Z")], async (tx) => {
      await tx.execute(sql`UPDATE notifications SET status_official = 'withdrawn'`);
      expect((await getZhWarnings(tx, { page: 1 }))?.items[0].withdrawn).toBe(true);
    });
  });

  it("is readable by the web role", async () => {
    await withRollback(
      async (tx) => {
        expect((await getZhWarnings(tx, { page: 1 }))?.page).toBe(1);
      },
      { role: "ofa_web" },
    );
  });
});

describe("parseZhWarningsPage", () => {
  it("accepts page numbers from 2 as written in canonical form", () => {
    expect(parseZhWarningsPage("2")).toBe(2);
    expect(parseZhWarningsPage("137")).toBe(137);
  });

  it("rejects page 1 (that is /zh/jinggao) and anything that is not a canonical number", () => {
    for (const segment of ["1", "0", "-2", "02", "2.0", "abc", "", "1e3", "99999999999"]) {
      expect(parseZhWarningsPage(segment), segment).toBeNull();
    }
  });
});
