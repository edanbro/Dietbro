import { createClerkClient } from "@clerk/backend";
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, test } from "@playwright/test";

/**
 * M2 acceptance: a new user can fully set up their profile on a phone.
 *
 * The user is created through Clerk's Backend API and signed in with a sign-in token
 * (Clerk's hosted sign-up form is Clerk's to test); everything after that is our UI.
 * The test ends by deleting the account through the app, and cleans up in Clerk regardless.
 */
test.skip(!process.env.CLERK_SECRET_KEY, "needs a Clerk dev instance (CLERK_SECRET_KEY)");

test("new user sets up goals, allergies, preferences and pantry on a phone", async ({ page }) => {
  const clerkClient = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY });
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;
  const email = `e2e+clerk_test+${stamp}@example.com`;
  const user = await clerkClient.users.createUser({
    emailAddress: [email],
    password: `Larder-e2e-${stamp}-${crypto.randomUUID()}`,
  });

  try {
    await setupClerkTestingToken({ page });
    await page.goto("/");
    await clerk.signIn({ page, emailAddress: email });
    await page.goto("/setup");

    // 1. Body stats are optional.
    await expect(page.getByRole("heading", { name: "About you" })).toBeVisible();
    await page.getByRole("button", { name: "Skip" }).click();

    // 2. Goals: an unsafe target is refused with a reason, a sensible one is accepted.
    await expect(page.getByRole("heading", { name: "Your goals" })).toBeVisible();
    await page.getByLabel("Goal").selectOption("maintain");
    await page.getByLabel("Min kcal / day").fill("900");
    await page.getByLabel("Max kcal / day").fill("1100");
    await page.getByRole("button", { name: "Save goals" }).click();
    await expect(page.getByRole("alert")).toContainText("calorie floor");
    await page.getByLabel("Min kcal / day").fill("1800");
    await page.getByLabel("Max kcal / day").fill("2200");
    await page.getByRole("button", { name: "Save goals" }).click();

    // 3. Allergies.
    await expect(page.getByRole("heading", { name: "Allergies" })).toBeVisible();
    await page.getByRole("checkbox", { name: "Peanuts" }).click();
    await page.getByRole("button", { name: "Save allergies" }).click();

    // 4. Preferences.
    await expect(page.getByRole("heading", { name: "What you like" })).toBeVisible();
    await page.getByLabel("Diet").selectOption("vegetarian");
    await page.getByRole("button", { name: "Save preferences" }).click();

    // 5. Pantry: search, pick, choose a count unit, add.
    await expect(page.getByRole("heading", { name: "What's in your kitchen" })).toBeVisible();
    await page.getByPlaceholder("Add food, e.g. onions").fill("onion");
    await page.getByRole("button", { name: /^Onions, raw/ }).click();
    await page.getByLabel("Quantity").fill("2");
    await page.getByLabel("Unit").selectOption("large");
    await page.getByRole("button", { name: "Add to pantry" }).click();
    await expect(page.getByRole("list", { name: "Pantry items" })).toContainText("Onions, raw");
    await page.getByRole("button", { name: "Done" }).click();

    // Setup done: the app opens on the (empty) plan.
    await expect(page).toHaveURL(/\/plan$/);
    await expect(page.getByRole("button", { name: "Plan my week" })).toBeVisible();
    await expect(page.getByText("Finish setting up")).toHaveCount(0);
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Pantry" }).click();
    await expect(page.getByRole("list", { name: "Pantry items" })).toContainText("2 large");

    // GDPR: delete the account from the profile page.
    await page.getByRole("link", { name: "Profile" }).click();
    await page.getByLabel('Type "delete" to confirm').fill("delete");
    await page.getByRole("button", { name: "Delete my account" }).click();
    await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
  } finally {
    await clerkClient.users.deleteUser(user.id).catch(() => undefined);
  }
});
