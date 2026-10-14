// Integration tests for the home page's "last 7 days" against TEST_DATABASE_URL. Each test
// replaces all Notifications inside a rolled-back transaction.
import { afterAll, describe, expect, it } from "vitest";
import { getRecentNotifications } from "./home";
import { testClient } from "./test-db";
import { withNotifications, type Row } from "./test-notifications";

afterAll(() => testClient.end());

// 25 October 2026, 14:00 in Amsterdam (CEST until 03:00 that night).
const NOW = new Date("2026-10-25T12:00:00Z");

const ROWS: Row[] = [
  { source: "rasff", key: "2026.0010", title: "Salmonella in chicken", publishedAt: "2026-10-24T08:00:00Z" },
  // 18 October 23:30 in Amsterdam: one day too early.
  { source: "rasff", key: "2026.0011", title: "Too early", publishedAt: "2026-10-18T21:30:00Z" },
  // 19 October 00:30 in Amsterdam: the first day of the window.
  { source: "rasff", key: "2026.0012", title: "First day", publishedAt: "2026-10-18T22:30:00Z" },
  // RASFF News is shown on pages (spec §4.3), only statistics leave it out.
  {
    source: "rasff",
    key: "2026.0013",
    title: "News about aflatoxins",
    publishedAt: "2026-10-23T08:00:00Z",
    notificationType: "news",
  },
  {
    source: "nvwa",
    key: "/actueel/nieuws/2026/10/22/veiligheidswaarschuwing-shampoo",
    title: "Shampoo",
    publishedAt: "2026-10-22T08:00:00Z",
    productType: "non-food",
  },
  {
    source: "nvwa",
    key: "/actueel/nieuws/2026/10/25/veiligheidswaarschuwing-kaas",
    title: "Listeria in kaas",
    publishedAt: "2026-10-25T09:00:00Z",
    notificationType: "veiligheidswaarschuwing",
  },
  { source: "openfda", key: "H-0001-2027", title: "Old recall", publishedAt: "2026-10-01T04:00:00Z" },
];

describe("getRecentNotifications", () => {
  it("lists the newest shown Notifications of the last 7 Amsterdam days per Source", async () => {
    await withNotifications(ROWS, async (tx) => {
      const r = await getRecentNotifications(tx, { locale: "en", now: NOW, perSource: 2 });
      expect(r.from).toBe("2026-10-19");
      expect(r.to).toBe("2026-10-25");
      expect(r.sources.map((s) => [s.source, s.label, s.total])).toEqual([
        ["rasff", "RASFF", 3],
        ["nvwa", "NVWA", 1],
        ["openfda", "openFDA", 0],
      ]);
      const [rasff, nvwa, openfda] = r.sources;
      expect(rasff.items).toEqual([
        {
          source: "rasff",
          sourceKey: "2026.0010",
          path: "/en/n/rasff/2026.0010",
          title: "Salmonella in chicken",
          publishedAt: "2026-10-24T08:00:00.000Z",
          notificationType: "alert notification",
        },
        expect.objectContaining({ sourceKey: "2026.0013", notificationType: "news" }),
      ]);
      expect(nvwa.items.map((i) => i.path)).toEqual([
        "/en/n/nvwa/actueel/nieuws/2026/10/25/veiligheidswaarschuwing-kaas",
      ]);
      expect(openfda.items).toEqual([]);
    });
  });

  it("links each Source to the same Notifications in search", async () => {
    await withNotifications(ROWS, async (tx) => {
      const r = await getRecentNotifications(tx, { locale: "nl", now: NOW });
      expect(r.sources[0].searchPath).toBe("/nl/search?source=rasff&from=2026-10-19");
      expect(r.sources[0].items[0].path).toBe("/nl/n/rasff/2026.0010");
    });
  });
});
