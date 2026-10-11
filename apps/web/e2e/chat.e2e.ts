import { createClerkClient } from "@clerk/backend";
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, type Page, test } from "@playwright/test";

/**
 * M4 acceptance: a vegetarian user with a peanut allergy tells the chat about a skipped dinner
 * and an off-plan lunch, and the plan shows both; the conversation survives a reload.
 *
 * Runs against an API *without* ANTHROPIC_API_KEY (as in CI): replies come from the offline
 * rule parser and the same executor, so the result is deterministic. Each chat turn re-plans,
 * so its steps wait up to 20 s.
 */
test.skip(!process.env.CLERK_SECRET_KEY, "needs a Clerk dev instance (CLERK_SECRET_KEY)");

const API = process.env.E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PLANNING = { timeout: 20_000 };
const CARD = /^(Plan updated|Logged)$/;

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

/** Send a message and wait until its reply is stored (the live bubble's status line is gone). */
async function say(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Message" }).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
  const log = page.getByRole("log", { name: "Conversation" });
  await expect(log.getByText(text, { exact: true })).toBeVisible();
  await expect(log.getByRole("status")).toHaveCount(0, PLANNING);
  return log;
}

async function openChat(page: Page) {
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Chat" }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

test("chat skips a dinner and logs an off-plan lunch, and the plan shows both", async ({
  page,
}) => {
  const clerkClient = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY });
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;
  const email = `e2e+clerk_test+chat${stamp}@example.com`;
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

    // 1. A plan for the week from today.
    await page.goto("/plan");
    await page.getByRole("button", { name: "Plan my week" }).click();
    await expect(page.getByRole("tablist", { name: "Day" }).getByRole("tab")).toHaveCount(
      7,
      PLANNING,
    );

    // 2. The chat starts empty, in simple (offline) mode.
    await openChat(page);
    await expect(page.getByRole("note")).toContainText("Simple replies: no AI key");
    await expect(page.getByText("Tell Larder what changed")).toBeVisible();

    // 3. Skip tonight's dinner: a card says so, and the plan shows the skip.
    let log = await say(page, "skip dinner tonight");
    const skip = log.getByRole("article", { name: CARD });
    await expect(skip).toHaveCount(1);
    await expect(skip).toContainText("Skipped today's dinner");
    await skip.getByRole("link", { name: "See plan" }).click();
    await expect(page).toHaveURL(/\/plan\?day=\d{4}-\d{2}-\d{2}$/);
    const meals = page.getByRole("list", { name: /^Meals on / });
    await expect(meals).toContainText("Skipped");
    await expect(page.getByRole("list", { name: "Planned without:" })).toContainText("Peanuts");

    // 4. Off-plan lunch: logged with an estimate, shown on the plan, counted in the totals.
    await openChat(page);
    log = await say(page, "had 2 slices of pizza for lunch");
    const cards = log.getByRole("article", { name: CARD });
    await expect(cards).toHaveCount(2);
    await expect(cards.nth(1)).toContainText(/pizza/i);
    await expect(cards.nth(1)).toContainText(/kcal/);
    await cards.nth(1).getByRole("link", { name: "See plan" }).click();
    await expect(meals).toContainText(/pizza \(off-plan, ~?[\d,]+ kcal/i);
    await expect(meals).toContainText("Skipped");
    await expect(page.getByText(/^Totals include .* kcal of logged food/)).toBeVisible();

    // 5. The conversation, cards included, survives a reload.
    await openChat(page);
    await page.reload();
    log = page.getByRole("log", { name: "Conversation" });
    await expect(log.getByRole("article", { name: CARD })).toHaveCount(2);
    await expect(log.getByText("skip dinner tonight", { exact: true })).toBeVisible();
    await expect(log.getByText("had 2 slices of pizza for lunch", { exact: true })).toBeVisible();

    // Clean up our data (the Clerk user goes in `finally`).
    const res = await page.request.delete(`${API}/me`, { headers: await authHeaders(page) });
    expect(res.ok()).toBe(true);
  } finally {
    await clerkClient.users.deleteUser(user.id).catch(() => undefined);
  }
});
