import { createClerkClient } from "@clerk/backend";
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, type Page, test } from "@playwright/test";
import { writeFileSync } from "node:fs";

/**
 * README media, not a test: `MEDIA=1 pnpm e2e media --project=phone` signs in a fresh account,
 * stocks a pantry, plans a week, then saves screenshots to docs/images/ and a walkthrough video
 * to test-results/ (scripts/readme-media.sh shrinks the stills and makes walkthrough.gif).
 */
test.skip(!process.env.MEDIA || !process.env.CLERK_SECRET_KEY, "run with MEDIA=1 and Clerk keys");
test.setTimeout(300_000);
test.use({ video: { mode: "on", size: { width: 412, height: 839 } } }); // the Pixel 7 viewport

const API = process.env.E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const OUT = "../../docs/images";

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

async function shot(page: Page, name: string, scheme: "light" | "dark" = "light") {
  await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

const PANTRY = ["chicken breast", "basmati rice", "broccoli", "eggs", "spinach", "carrots"];

test("README screenshots and walkthrough", async ({ page }, info) => {
  const t0 = Date.now(); // the video starts about when the page does
  const clerkClient = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY });
  const stamp = `${Date.now()}`;
  const user = await clerkClient.users.createUser({
    emailAddress: [`e2e+clerk_test+media${stamp}@example.com`],
    password: `Larder-e2e-${stamp}-${crypto.randomUUID()}`,
  });
  try {
    await page.goto("/");
    await setupClerkTestingToken({ page });
    await clerk.signIn({ page, emailAddress: `e2e+clerk_test+media${stamp}@example.com` });
    await api(page, "PUT", "/me/region", { country: "IE", timezone: "Europe/Dublin", locale: "en-IE" });
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
    for (const q of PANTRY) {
      const [food] = await api(page, "GET", `/foods/search?q=${encodeURIComponent(q)}&scope=generic`);
      if (food) await api(page, "POST", "/pantry", { food_id: food.id, quantity: 500, unit: "g" });
    }
    const today = new Date();
    for (let i = 6; i >= 0; i--) {
      const d = new Date(today.getTime() - i * 86_400_000).toISOString().slice(0, 10);
      await api(page, "PUT", "/me/weights", { measured_on: d, weight_kg: 78.4 - i * 0.15 });
    }

    // The walkthrough (recorded): plan a week, open a dinner, cook mode, the shopping list.
    await page.goto("/plan");
    await page.getByRole("button", { name: "Plan my week" }).waitFor();
    const start = (Date.now() - t0) / 1000;
    await page.getByRole("button", { name: "Plan my week" }).click();
    const meals = page.getByRole("list", { name: /^Meals on / });
    await expect(meals.getByRole("link").first()).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(1200);
    await page.mouse.wheel(0, 500);
    await page.waitForTimeout(900);
    await page.mouse.wheel(0, -500);
    const dinner = meals.getByRole("listitem").filter({ hasText: "Dinner" }).getByRole("link");
    await dinner.click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForTimeout(1200);
    await page.getByRole("link", { name: /Start cooking/ }).click();
    await page.waitForTimeout(1500);
    await page.goto("/plan/shopping");
    await expect(page.getByRole("heading", { name: "Shopping list" })).toBeVisible();
    await page.waitForTimeout(800);
    await page.getByRole("checkbox").first().click();
    await page.waitForTimeout(400);
    await page.getByRole("checkbox").nth(1).click();
    await page.waitForTimeout(1200);

    // Where the walkthrough is in the video, for scripts/readme-media.sh.
    writeFileSync(
      info.outputPath("walkthrough.txt"),
      `${start.toFixed(1)} ${((Date.now() - t0) / 1000).toFixed(1)}\n`,
    );

    // Stills.
    const plan = await api(page, "GET", "/plans/current");
    const first = plan.days[0].meals.find((m: { slot: string }) => m.slot === "breakfast");
    if (first) {
      await api(page, "POST", `/plans/${plan.id}/meals/eaten`, {
        today: plan.days[0].date,
        date: plan.days[0].date,
        slot: "breakfast",
      });
    }
    await page.goto("/plan");
    await shot(page, "plan");
    await shot(page, "plan-dark", "dark");
    const withPhoto = plan.days
      .flatMap((d: { meals: { slot: string; recipe: { id: number; image_url: string | null } }[] }) => d.meals)
      .find((m: { slot: string; recipe: { image_url: string | null } }) => m.slot === "dinner" && m.recipe.image_url);
    if (withPhoto) {
      await page.goto(`/recipes/${withPhoto.recipe.id}`);
      await shot(page, "recipe");
      await page.goto(`/recipes/${withPhoto.recipe.id}/cook?servings=2`);
      await shot(page, "cook");
    }
    await page.goto("/plan/shopping");
    await shot(page, "shopping");
    await page.goto("/pantry");
    await shot(page, "pantry");
    await page.goto("/diary");
    await page.getByRole("heading", { name: "Weight" }).scrollIntoViewIfNeeded();
    await page.mouse.wheel(0, 120);
    await shot(page, "diary");
    await page.goto("/recipes/import");
    await shot(page, "import");

    await api(page, "DELETE", "/me");
  } finally {
    await clerkClient.users.deleteUser(user.id).catch(() => undefined);
  }
});
