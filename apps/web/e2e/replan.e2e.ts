import { createClerkClient } from "@clerk/backend";
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, type Page, test } from "@playwright/test";

/**
 * M5 acceptance: on a fresh plan the user marks today's breakfast eaten and undoes it, then
 * skips tomorrow's dinner from the plan screen and sees what changed.
 *
 * Time of day doesn't matter: breakfast can be marked eaten at any hour (it is on or before
 * today), and a skip is a fact, so tomorrow's dinner can always be skipped. The replan runs the
 * real planner (no model calls), so its step waits up to 20 s.
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

/** Wait for the API's answer to a plan change and check it succeeded. */
function planChange(page: Page, method: string, path: string) {
  return page.waitForResponse(
    (r) => r.request().method() === method && new URL(r.url()).pathname.endsWith(path),
    PLANNING,
  );
}

test("marks a meal eaten, undoes it, and skips a later meal from the plan", async ({ page }) => {
  const clerkClient = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY });
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;
  const email = `e2e+clerk_test+replan${stamp}@example.com`;
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

    // 1. A plan for the week from today; the day view opens on today.
    await page.goto("/plan");
    await page.getByRole("button", { name: "Plan my week" }).click();
    const days = page.getByRole("tablist", { name: "Day" }).getByRole("tab");
    await expect(days).toHaveCount(7, PLANNING);
    await expect(days.first()).toHaveAttribute("aria-selected", "true");
    const meals = page.getByRole("list", { name: /^Meals on / });
    const breakfast = meals.getByRole("listitem").first();
    await expect(breakfast).toContainText("Breakfast");

    // 2. Mark today's breakfast eaten: the card gets its badge, the options shrink to undo.
    await breakfast.getByRole("button", { name: "Breakfast options" }).click();
    let saved = planChange(page, "POST", "/meals/eaten");
    await breakfast.getByRole("button", { name: "Mark eaten" }).click();
    expect((await saved).ok()).toBe(true);
    await expect(page.getByText("Breakfast marked eaten")).toBeVisible();
    await expect(breakfast.getByRole("link")).toContainText("Eaten");

    // 3. Undo it.
    await breakfast.getByRole("button", { name: "Breakfast options" }).click();
    const options = breakfast.getByRole("group", { name: "Breakfast options" });
    await expect(options.getByRole("button")).toHaveText(["Undo eaten"]);
    saved = planChange(page, "DELETE", "/meals/eaten");
    await options.getByRole("button", { name: "Undo eaten" }).click();
    expect((await saved).ok()).toBe(true);
    await expect(breakfast.getByRole("link")).not.toContainText("Eaten");

    // 4. Skip tomorrow's dinner (not eating): the plan says what changed and shows the skip.
    await days.nth(1).click();
    await expect(days.nth(1)).toHaveAttribute("aria-selected", "true");
    await meals.getByRole("button", { name: "Dinner options" }).click();
    await meals.getByRole("button", { name: "Skip" }).click();
    saved = planChange(page, "POST", "/plans/replan");
    await meals.getByRole("button", { name: "No, I'm not eating" }).click();
    expect((await saved).ok()).toBe(true);
    const changed = page.getByRole("region", { name: "What changed" });
    await expect(changed).toBeVisible();
    await expect(changed.getByRole("list", { name: "Logged food" })).toContainText(
      /Skipped \w+ dinner/,
    );
    await expect(meals).toContainText("Skipped");
    await expect(meals.getByRole("button", { name: "Dinner options" })).toHaveCount(0);

    // Clean up our data (the Clerk user goes in `finally`).
    const res = await page.request.delete(`${API}/me`, { headers: await authHeaders(page) });
    expect(res.ok()).toBe(true);
  } finally {
    await clerkClient.users.deleteUser(user.id).catch(() => undefined);
  }
});
