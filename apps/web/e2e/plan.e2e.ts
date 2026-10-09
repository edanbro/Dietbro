import { createClerkClient } from "@clerk/backend";
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, type Page, test } from "@playwright/test";

/**
 * M3 acceptance: a set-up user plans a week on a phone, opens a recipe and ticks the shopping
 * list. The profile is saved through the API (the setup wizard has its own test); everything
 * after that is our UI. Planning runs the real planner, so its steps wait up to 20 s.
 */
test.skip(!process.env.CLERK_SECRET_KEY, "needs a Clerk dev instance (CLERK_SECRET_KEY)");

const API = process.env.E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PLANNING = { timeout: 20_000 };

type ClerkWindow = { Clerk: { session: { getToken(): Promise<string | null> } | null } };

async function authHeaders(page: Page) {
  const token = await page.evaluate(() =>
    (window as unknown as ClerkWindow).Clerk.session?.getToken(),
  );
  expect(token, "signed-in session token").toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

async function apiPut(page: Page, path: string, data: unknown) {
  const res = await page.request.put(`${API}${path}`, { headers: await authHeaders(page), data });
  expect(res.ok(), `PUT ${path}: ${res.status()} ${await res.text()}`).toBe(true);
}

test("set-up user plans a week, opens a recipe and ticks the shopping list", async ({ page }) => {
  const clerkClient = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY });
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;
  const email = `e2e+clerk_test+plan${stamp}@example.com`;
  const user = await clerkClient.users.createUser({
    emailAddress: [email],
    password: `Larder-e2e-${stamp}-${crypto.randomUUID()}`,
  });

  try {
    await setupClerkTestingToken({ page });
    await page.goto("/");
    await clerk.signIn({ page, emailAddress: email });

    await apiPut(page, "/me/goals", {
      goal: "maintain",
      kcal_min: 1800,
      kcal_max: 2200,
      calorie_floor: 1200,
      max_daily_deficit: 1000,
      currency: "GBP",
    });
    await apiPut(page, "/me/allergies", { allergens: ["peanuts"], avoid_food_ids: [] });
    await apiPut(page, "/me/preferences", { diet: "vegetarian" });

    // 1. Plan the week.
    await page.goto("/plan");
    await page.getByRole("button", { name: "Plan my week" }).click();
    const days = page.getByRole("tablist", { name: "Day" }).getByRole("tab");
    await expect(days).toHaveCount(7, PLANNING);
    const without = page.getByRole("list", { name: "Planned without:" });
    await expect(without).toContainText("Peanuts");
    await expect(without).toContainText("Vegetarian");

    // 2. Seven days, each with breakfast, lunch and dinner (the week grid shows them all).
    await page.getByRole("tab", { name: "Week" }).click();
    const grid = page.getByRole("table", { name: "Meals this week" });
    await expect(grid.getByRole("columnheader")).toContainText(["Breakfast", "Lunch", "Dinner"]);
    const rows = grid.getByRole("row");
    await expect(rows).toHaveCount(8);
    for (let day = 1; day <= 7; day++) {
      const cells = rows.nth(day).getByRole("cell");
      for (let slot = 0; slot < 3; slot++) {
        await expect(cells.nth(slot).getByRole("link")).toHaveCount(1);
      }
    }

    // 3. Open a recipe from the day view.
    await page.getByRole("tab", { name: "Day", exact: true }).click();
    const meals = page.getByRole("list", { name: /^Meals on / });
    await meals.getByRole("link").first().click();
    await expect(page).toHaveURL(/\/recipes\/\d+$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Ingredients" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Allergens" })).toBeVisible();

    // 4. Shopping list: tick an item; it stays ticked after a reload.
    await page.getByRole("button", { name: "Back" }).click();
    await expect(page).toHaveURL(/\/plan/);
    await page.getByRole("link", { name: "Shopping" }).click();
    await expect(page.getByRole("heading", { name: "Shopping list" })).toBeVisible();
    const box = page.getByRole("checkbox").first();
    await expect(box).toHaveAttribute("aria-checked", "false");
    const saved = page.waitForResponse(
      (r) => r.request().method() === "PATCH" && r.url().includes("/shopping/"),
    );
    await box.click();
    await expect(box).toHaveAttribute("aria-checked", "true");
    expect((await saved).ok()).toBe(true);
    await page.reload();
    await expect(page.getByRole("checkbox").first()).toHaveAttribute("aria-checked", "true");

    // Clean up our data (the Clerk user goes in `finally`).
    const res = await page.request.delete(`${API}/me`, { headers: await authHeaders(page) });
    expect(res.ok()).toBe(true);
  } finally {
    await clerkClient.users.deleteUser(user.id).catch(() => undefined);
  }
});
