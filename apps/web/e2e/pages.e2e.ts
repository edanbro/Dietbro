import AxeBuilder from "@axe-core/playwright";
import { createClerkClient } from "@clerk/backend";
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, type Page, test } from "@playwright/test";

/**
 * Every main page, light and dark: no serious or critical accessibility problems (axe, WCAG
 * 2.1 A/AA). With SHOTS=1 it also saves a full-page screenshot of each into e2e-shots/ for
 * design review (not compared: plans change with the date, so pixel baselines would churn).
 */
test.skip(!process.env.CLERK_SECRET_KEY, "needs a Clerk dev instance (CLERK_SECRET_KEY)");
test.setTimeout(240_000);

const API = process.env.E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SHOTS = !!process.env.SHOTS;

type ClerkWindow = { Clerk: { session: { getToken(): Promise<string | null> } | null } };

async function api(
  page: Page,
  method: "GET" | "PUT" | "POST" | "DELETE",
  path: string,
  data?: unknown,
) {
  const token = await page.evaluate(() =>
    (window as unknown as ClerkWindow).Clerk.session?.getToken(),
  );
  const res = await page.request.fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  expect(res.ok(), `${method} ${path}: ${res.status()} ${await res.text()}`).toBe(true);
  return res;
}

async function check(page: Page, name: string, scheme: "light" | "dark", project: string) {
  await page.emulateMedia({ colorScheme: scheme });
  await page.waitForLoadState("networkidle");
  // Let entrance transitions settle so contrast is measured on final colours.
  await page.waitForTimeout(400);
  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const bad = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const report = bad.map(
    (v) => `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes.map((n) => n.target.join(" ")).join("\n  ")}`,
  );
  expect.soft(report, `${name} (${scheme})`).toEqual([]);
  if (SHOTS) {
    await page.screenshot({ path: `e2e-shots/${project}/${name}-${scheme}.png`, fullPage: true });
  }
}

test("main pages pass accessibility checks in light and dark", async ({ page }, info) => {
  const clerkClient = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY });
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;
  const email = `e2e+clerk_test+pages${stamp}@example.com`;
  const user = await clerkClient.users.createUser({
    emailAddress: [email],
    password: `Larder-e2e-${stamp}-${crypto.randomUUID()}`,
  });
  const visit = async (name: string, path: string) => {
    await page.goto(path);
    for (const scheme of ["light", "dark"] as const) {
      await check(page, name, scheme, info.project.name);
    }
  };

  try {
    await page.goto("/");
    await visit("landing", "/");

    await setupClerkTestingToken({ page });
    await clerk.signIn({ page, emailAddress: email });
    await api(page, "PUT", "/me/goals", {
      goal: "maintain",
      kcal_min: 1800,
      kcal_max: 2200,
      calorie_floor: 1200,
      max_daily_deficit: 1000,
      currency: "EUR",
    });
    await api(page, "PUT", "/me/allergies", { allergens: ["peanuts"], avoid_food_ids: [] });
    await api(page, "PUT", "/me/preferences", {});


    await page.goto("/plan");
    await page.getByRole("button", { name: "Plan my week" }).click();
    const meals = page.getByRole("list", { name: /^Meals on / });
    await expect(meals.getByRole("link").first()).toBeVisible({ timeout: 30_000 });
    const href = await meals.getByRole("link").first().getAttribute("href");
    const recipe = href?.match(/\/recipes\/\d+/)?.[0];
    expect(recipe, "a planned recipe link").toBeTruthy();

    await visit("plan", "/plan");
    await visit("shopping", "/plan/shopping");
    await visit("pantry", "/pantry");
    await visit("receipts", "/pantry/receipts");
    await visit("recipes", "/recipes");
    await visit("recipe", recipe!);
    await visit("cook", `${recipe}/cook`);
    await visit("prep", `/prep?r=${recipe!.split("/").at(-1)}x2`);
    await visit("diary", "/diary");
    await visit("recap", "/recap");
    await visit("chat", "/chat");
    await visit("profile", "/profile");
    await visit("setup", "/setup");

    // Public share pages (no sign-in needed to view them).
    const recipeId = Number(recipe!.split("/").at(-1));
    const recipeLink = await api(page, "POST", "/share", { kind: "recipe", recipe_id: recipeId });
    const plan = await (await api(page, "GET", "/plans/current")).json();
    const weekLink = await api(page, "POST", "/share", { kind: "week", start: plan.start });
    await visit("shared-recipe", (await recipeLink.json()).path);
    await visit("shared-week", (await weekLink.json()).path);

    await api(page, "DELETE", "/me");
  } finally {
    await clerkClient.users.deleteUser(user.id).catch(() => undefined);
  }
});
