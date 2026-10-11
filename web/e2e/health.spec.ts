// Smoke test for GET /api/health against the running server. The fixture database has no
// ingest runs or contract probes, so the status depends on the database, not on the test:
// only the shape and the agreement between status code and body are checked.
import { expect, test } from "@playwright/test";

test("GET /api/health reports every Source and is never cached", async ({ request }) => {
  const response = await request.get("/api/health");
  expect([200, 503]).toContain(response.status());
  expect(response.headers()["cache-control"]).toContain("no-store");
  const body = await response.json();
  expect(body.status).toBe(response.status() === 200 ? "ok" : "degraded");
  expect(body.thresholds).toEqual({ freshHours: 36, rasffSilenceDays: 7 });
  expect(body.sources.map((s: { source: string }) => s.source)).toEqual([
    "rasff",
    "nvwa",
    "openfda",
  ]);
  for (const s of body.sources) {
    expect(Object.keys(s).sort()).toEqual(
      [
        "contract",
        "fresh",
        "lastErrorAt",
        "lastSuccessAt",
        "name",
        "newNotifications",
        "ok",
        "problems",
        "silent",
        "source",
      ].sort(),
    );
    expect(s.ok).toBe(s.problems.length === 0);
  }

  // Computed per request: checkedAt moves on.
  const again = await (await request.get("/api/health")).json();
  expect(Date.parse(again.checkedAt)).toBeGreaterThanOrEqual(Date.parse(body.checkedAt));
  expect(again.checkedAt).not.toBe(body.checkedAt);
});
