import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a running web app + API (see .github/workflows/ci.yml `e2e` job).
 * They need a Clerk *development* instance: CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY.
 * Without those the tests skip.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /global\.setup\.ts/ },
    {
      name: "phone",
      testMatch: /.*\.e2e\.ts/,
      use: { ...devices["Pixel 7"] },
      dependencies: ["setup"],
    },
  ],
});
