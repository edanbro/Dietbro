import { createClerkClient } from "@clerk/backend";
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { type BrowserContext, expect, type Page, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";

/**
 * Visual comparison: every main page, light and dark, at the project's size (visual-phone,
 * visual-desktop), against committed screenshots in e2e/__screenshots__/. Deterministic: the
 * API is replayed from a recording (e2e/visual/api.har), the page clock is frozen at the
 * recording's time, images are one flat placeholder, motion is off, service workers are off.
 *
 * - Compare or update: `make visual` / `make visual-update` (scripts/visual.sh). They run in the
 *   Playwright Linux container, so fonts and anti-aliasing match CI; screenshots from Windows
 *   or macOS would differ by a few pixels everywhere.
 * - Record: `VISUAL_RECORD=1 pnpm e2e visual --project=setup --project=visual-phone` against the
 *   local stack (seeded). Signs in a fresh account, stocks a pantry, plans a week, visits every
 *   page and saves the API's answers, sign-in headers removed. Re-record when an API response
 *   changes shape, then update the screenshots.
 */
const RECORD = !!process.env.VISUAL_RECORD;
test.skip(
  !(RECORD || process.env.VISUAL) || !process.env.CLERK_SECRET_KEY,
  "VISUAL=1 or VISUAL_RECORD=1, with Clerk keys (make visual)",
);
test.setTimeout(300_000);
test.use({
  serviceWorkers: "block", // the PWA's worker would answer from its cache, past the recording
  timezoneId: "Europe/Dublin",
  locale: "en-IE",
});

const API = process.env.E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const HAR = "e2e/visual/api.har";
const META = "e2e/visual/meta.json";
type Meta = { recordedAt: string; recipeId: number };

const PAGES = (recipeId: number): [string, string][] => [
  ["plan", "/plan"],
  ["shopping", "/plan/shopping"],
  ["pantry", "/pantry"],
  ["recipes", "/recipes"],
  ["recipe", `/recipes/${recipeId}`],
  ["cook", `/recipes/${recipeId}/cook`],
  ["diary", "/diary"],
  ["chat", "/chat"],
  ["profile", "/profile"],
  ["setup", "/setup"],
];

type ClerkWindow = { Clerk: { session: { getToken(): Promise<string | null> } | null } };

async function api(page: Page, method: string, path: string, data?: unknown) {
  const token = await page.evaluate(() =>
    (window as unknown as ClerkWindow).Clerk.session?.getToken(),
  );
  const res = await page.request.fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  expect(res.ok(), `${method} ${path}: ${res.status()} ${await res.text()}`).toBe(true);
  return res.status() === 204 ? null : res.json();
}

/** A fresh Clerk test user, signed in on `page`; returns a function that deletes it. */
async function signIn(page: Page): Promise<() => Promise<void>> {
  const clerkClient = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY });
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;
  const email = `e2e+clerk_test+visual${stamp}@example.com`;
  const user = await clerkClient.users.createUser({
    emailAddress: [email],
    password: `Larder-e2e-${stamp}-${crypto.randomUUID()}`,
  });
  await setupClerkTestingToken({ page });
  await clerk.signIn({ page, emailAddress: email });
  return async () => {
    await clerkClient.users.deleteUser(user.id).catch(() => undefined);
  };
}

// A 1x1 grey PNG for every photo (recipe photos, product photos, Next's image optimiser).
const PLACEHOLDER = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN8+P9/PQAI2ANlsRyXkQAAAABJRU5ErkJggg==",
  "base64",
);

async function stillImages(context: BrowserContext) {
  await context.route(
    (url) => url.pathname.startsWith("/_next/image") || !url.hostname.match(/^(localhost|127\.)/),
    async (route) => {
      if (route.request().resourceType() !== "image") return route.fallback();
      await route.fulfill({ contentType: "image/png", body: PLACEHOLDER });
    },
  );
}

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
}

/** Sign-in headers and cookies out of the recording (they are short-lived, but never commit
 * them); everything else stays. */
function scrub(path: string) {
  const har = JSON.parse(readFileSync(path, "utf-8"));
  const secret = /^(authorization|cookie|set-cookie)$/i;
  for (const entry of har.log.entries) {
    entry.request.headers = entry.request.headers.filter(
      (h: { name: string }) => !secret.test(h.name),
    );
    entry.request.cookies = [];
    entry.response.headers = entry.response.headers.filter(
      (h: { name: string }) => !secret.test(h.name),
    );
    entry.response.cookies = [];
  }
  writeFileSync(path, `${JSON.stringify(har, null, 1)}\n`);
}

test("record the API for the visual comparison", async ({ browser }) => {
  test.skip(!RECORD, "VISUAL_RECORD=1");
  const context = await browser.newContext({
    serviceWorkers: "block",
    timezoneId: "Europe/Dublin",
    locale: "en-IE",
    baseURL: test.info().project.use.baseURL,
  });
  const page = await context.newPage();
  await page.goto("/");
  const done = await signIn(page);
  try {
    await api(page, "PUT", "/me/region", {
      country: "IE",
      timezone: "Europe/Dublin",
      locale: "en-IE",
    });
    await api(page, "PUT", "/me/goals", {
      goal: "maintain",
      kcal_min: 1900,
      kcal_max: 2300,
      protein_g_min: 110,
      calorie_floor: 1200,
      max_daily_deficit: 1000,
      currency: "EUR",
      weekly_budget_minor: 7000,
    });
    await api(page, "PUT", "/me/allergies", { allergens: ["peanuts"], avoid_food_ids: [] });
    await api(page, "PUT", "/me/preferences", {});
    for (const q of ["chicken breast", "basmati rice", "broccoli", "eggs", "spinach", "carrots"]) {
      const [food] = await api(
        page,
        "GET",
        `/foods/search?q=${encodeURIComponent(q)}&scope=generic`,
      );
      if (food) await api(page, "POST", "/pantry", { food_id: food.id, quantity: 500, unit: "g" });
    }
    const now = new Date();
    for (let i = 6; i >= 0; i--) {
      const d = new Date(now.getTime() - i * 86_400_000).toISOString().slice(0, 10);
      await api(page, "PUT", "/me/weights", { measured_on: d, weight_kg: 78.4 - i * 0.15 });
    }
    const plan = await api(page, "POST", "/plans", {});
    await api(page, "POST", `/plans/${plan.id}/meals/eaten`, {
      today: plan.days[0].date,
      date: plan.days[0].date,
      slot: "breakfast",
    });
    await api(page, "POST", "/shopping/extras", { name: "Bin bags" });
    await api(page, "POST", "/me/templates", { name: "Busy weeknights", start: plan.start });
    const dinner = plan.days[0].meals.find((m: { slot: string }) => m.slot === "dinner");
    const meta: Meta = { recordedAt: new Date().toISOString(), recipeId: dinner.recipe.id };

    await context.routeFromHAR(HAR, { url: `${API}/**`, update: true, updateContent: "embed" });
    for (const [, path] of PAGES(meta.recipeId)) {
      await page.goto(path);
      await settle(page);
    }
    writeFileSync(META, `${JSON.stringify(meta, null, 2)}\n`);
    await api(page, "DELETE", "/me");
  } finally {
    await context.close(); // writes the HAR
    await done();
  }
  scrub(HAR);
});

test("pages match their screenshots", async ({ page, context }) => {
  test.skip(RECORD, "recording");
  const meta: Meta = JSON.parse(readFileSync(META, "utf-8"));
  await page.clock.setFixedTime(new Date(meta.recordedAt));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await stillImages(context);
  const shot = async (name: string) => {
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await settle(page);
      await expect.soft(page, `${name} (${scheme})`).toHaveScreenshot(`${name}-${scheme}.png`, {
        fullPage: true,
        // The account menu shows the signed-in test user, different every run.
        mask: [page.locator(".cl-userButtonTrigger, .cl-avatarBox")],
      });
    }
  };

  await page.goto("/");
  await shot("landing");

  const done = await signIn(page);
  try {
    await context.routeFromHAR(HAR, { url: `${API}/**`, notFound: "abort" });
    for (const [name, path] of PAGES(meta.recipeId)) {
      await page.goto(path);
      await shot(name);
    }
  } finally {
    await done();
  }
});
