import { createClerkClient } from "@clerk/backend";
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, type Page, test } from "@playwright/test";

/**
 * M6 acceptance: a user pastes a receipt, the worker reads it, they fix a use-by date, reject a
 * line, confirm, and find the food in their pantry with an expiry alert. Needs the arq worker
 * running (the CI e2e job starts it) and the seeded catalog: these three lines match there
 * (milk and chopped tomatoes through the receipt vocabulary, bananas through the aliases; see
 * docs/receipt-accuracy.md).
 */
test.skip(!process.env.CLERK_SECRET_KEY, "needs a Clerk dev instance (CLERK_SECRET_KEY)");

const API = process.env.E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
/** Pasted text takes ~0.1 s in the worker; allow for a cold worker and a slow runner. */
const READING = { timeout: 30_000 };

const RECEIPT = [
  "E2E MART",
  "SEMI SKMD MILK 4PT              £1.45",
  "2 x CHOPPED TOMS 400G           £1.10",
  "BANANAS LOOSE                   £0.68",
  "TOTAL                           £3.23",
  "VISA                            £3.23",
].join("\n");

type ClerkWindow = { Clerk: { session: { getToken(): Promise<string | null> } | null } };

async function authHeaders(page: Page) {
  const token = await page.evaluate(() =>
    (window as unknown as ClerkWindow).Clerk.session?.getToken(),
  );
  expect(token, "signed-in session token").toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

test("user adds food from a pasted receipt and sees what expires soon", async ({ page }) => {
  const clerkClient = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY });
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;
  const email = `e2e+clerk_test+receipt${stamp}@example.com`;
  const user = await clerkClient.users.createUser({
    emailAddress: [email],
    password: `Larder-e2e-${stamp}-${crypto.randomUUID()}`,
  });

  try {
    await setupClerkTestingToken({ page });
    await page.goto("/");
    await clerk.signIn({ page, emailAddress: email });

    // 1. Paste the receipt.
    await page.goto("/pantry");
    await page.getByRole("link", { name: "Add from receipt" }).click();
    await expect(page.getByRole("heading", { name: "Add from receipt" })).toBeVisible();
    await page.getByRole("tab", { name: "Paste text" }).click();
    await page.getByLabel("Receipt text", { exact: true }).fill(RECEIPT);
    await page.getByRole("button", { name: "Read receipt" }).click();
    await expect(page).toHaveURL(/\/pantry\/receipts\/\d+$/);

    // 2. The worker reads it: three item lines, each matched to a food.
    const lines = page.getByRole("list", { name: "Receipt lines" });
    await expect(lines).toBeVisible(READING);
    await expect(lines.getByRole("listitem")).toHaveCount(3);
    await expect(lines).not.toContainText("No match");
    await expect(page.getByText("3 items will be added")).toBeVisible();

    // 3. Milk goes off tomorrow (the browser's local date), not in a week.
    const tomorrow = await page.evaluate(() => {
      const d = new Date();
      d.setDate(d.getDate() + 1);
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    });
    const milk = lines.getByRole("listitem").filter({ hasText: "SEMI SKMD MILK" });
    await milk.getByRole("button", { name: /^Edit / }).click();
    const edit = milk.getByRole("form", { name: /^Edit / });
    await edit.getByLabel("Use by", { exact: true }).fill(tomorrow);
    await edit.getByRole("button", { name: "Save" }).click();
    await expect(edit).toBeHidden();

    // 4. Not the bananas.
    const bananas = lines.getByRole("listitem").filter({ hasText: "BANANAS LOOSE" });
    await bananas.getByRole("button", { name: /^Reject / }).click();
    await expect(bananas).toContainText("Won't be added");
    await expect(page.getByText("2 items will be added")).toBeVisible();

    // 5. Confirm: back on the pantry with both items and an alert for the milk.
    await page.getByRole("button", { name: "Add 2 items to pantry" }).click();
    await expect(page.getByText("Added 2 items to your pantry")).toBeVisible();
    await expect(page).toHaveURL(/\/pantry$/);
    const pantry = page.getByRole("list", { name: "Pantry items" });
    await expect(pantry.getByRole("listitem")).toHaveCount(2);
    await expect(pantry).toContainText(/milk/i);
    await expect(pantry).toContainText(/tomatoes/i);
    await expect(pantry).not.toContainText(/banana/i);
    const alerts = page.getByRole("region", { name: "Use soon" });
    await expect(alerts).toContainText(/milk/i);
    await expect(alerts).toContainText("expires tomorrow");
    await expect(page.getByRole("link", { name: "Pantry, 1 expiring soon" })).toBeVisible();

    // 6. The receipt is listed as added.
    await page.getByRole("link", { name: "Add from receipt" }).click();
    await expect(
      page.getByRole("region", { name: "Recent receipts" }).getByRole("link").first(),
    ).toContainText("Added");

    // Clean up our data (the Clerk user goes in `finally`).
    const res = await page.request.delete(`${API}/me`, { headers: await authHeaders(page) });
    expect(res.ok()).toBe(true);
  } finally {
    await clerkClient.users.deleteUser(user.id).catch(() => undefined);
  }
});
