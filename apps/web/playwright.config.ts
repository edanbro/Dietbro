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
    // Locally without Playwright's own Chromium: E2E_CHANNEL=msedge (or chrome).
    channel: process.env.E2E_CHANNEL,
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /global\.setup\.ts/ },
    {
      name: "phone",
      testMatch: /.*\.e2e\.ts/,
      testIgnore: /visual\.e2e\.ts/,
      use: { ...devices["Pixel 7"] },
      dependencies: ["setup"],
    },
    {
      name: "desktop",
      testMatch: /pages\.e2e\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
      dependencies: ["setup"],
    },
    // Screenshot comparison (e2e/visual.e2e.ts): made and compared in the Playwright Linux
    // container only (make visual), so the names carry no platform.
    ...(["phone", "desktop"] as const).map((size) => ({
      name: `visual-${size}`,
      testMatch: /visual\.e2e\.ts/,
      snapshotPathTemplate: `{testDir}/__screenshots__/${size}/{arg}{ext}`,
      use:
        size === "phone"
          ? { ...devices["Pixel 7"] }
          : { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
      dependencies: ["setup"],
    })),
  ],
  expect: {
    // Small rendering noise is allowed; a moved, missing or recoloured element is not.
    toHaveScreenshot: { maxDiffPixelRatio: 0.002, animations: "disabled", caret: "hide" },
  },
});
