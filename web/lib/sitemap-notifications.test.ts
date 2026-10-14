// Integration test for the sitemap's Notification list against TEST_DATABASE_URL.
import { sql } from "drizzle-orm";
import { afterAll, describe, expect, it } from "vitest";
import { listSitemapNotifications } from "./notifications";
import { testClient } from "./test-db";
import { withNotifications } from "./test-notifications";

afterAll(() => testClient.end());

describe("listSitemapNotifications", () => {
  it("lists shown Notifications, most recently published first, with their last change", async () => {
    await withNotifications(
      [
        { source: "rasff", key: "2026.0001", title: "Older", publishedAt: "2026-10-01T08:00:00Z" },
        { source: "openfda", key: "H-0002-2027", title: "Newer", publishedAt: "2026-10-20T08:00:00Z" },
        { source: "nvwa", key: "/actueel/x", title: "Not food", productType: "non-food" },
        { source: "openfda", key: "Z-0003-2027", title: "Pending", productType: null },
        { source: "rasff", key: "2026.0004", title: "Newest", publishedAt: "2026-10-22T08:00:00Z" },
      ],
      async (tx) => {
        await tx.execute(
          sql`UPDATE notifications SET last_changed_at = '2026-10-23T09:30:00Z' WHERE source_key = 'H-0002-2027'`,
        );
        const listed = await listSitemapNotifications(tx, 2);
        expect(listed).toEqual([
          { source: "rasff", key: "2026.0004", lastChangedAt: expect.any(String) },
          { source: "openfda", key: "H-0002-2027", lastChangedAt: "2026-10-23T09:30:00.000Z" },
        ]);
        expect((await listSitemapNotifications(tx, 10)).map((n) => n.key)).toEqual([
          "2026.0004",
          "H-0002-2027",
          "2026.0001",
        ]);
      },
    );
  });
});
