import { defineConfig, devices } from "@playwright/test";
import { OUTBOX_DIR } from "./e2e/outbox";

// `make smoke` loads the fixtures and builds first; this config only starts the server.
const port = Number(process.env.SMOKE_PORT ?? 3004);

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: `http://localhost:${port}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `pnpm start --port ${port}`,
    url: `http://localhost:${port}/en`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      // Emails go to e2e/.outbox, never to a real provider.
      EMAIL_TRANSPORT: "outbox",
      EMAIL_OUTBOX_DIR: OUTBOX_DIR,
      OFA_HASH_PEPPER: process.env.OFA_HASH_PEPPER ?? "smoke-test-pepper",
      OFA_TOKEN_SECRET: process.env.OFA_TOKEN_SECRET ?? "smoke-test-token-secret",
      // All tests share one IP; keep the per-IP limit out of the way.
      SUBSCRIBE_RATE_LIMIT: "200/600",
      CONFIRM_RATE_LIMIT: "200/600",
      MANAGE_RATE_LIMIT: "500/600",
    },
  },
});
