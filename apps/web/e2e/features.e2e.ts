import { createClerkClient } from "@clerk/backend";
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, type Page, test } from "@playwright/test";

/**
 * The newer features end to end, on the real API: quick-add to the diary, typing a recipe in
 * (then rating it, a note, and an edit),
 * a share link (seen signed out, then revoked), the calendar feed, cooking extra for
 * tomorrow's lunch, saving a week as a template and planning from it, and copying a day.
 */
test.skip(!process.env.CLERK_SECRET_KEY, "needs a Clerk dev instance (CLERK_SECRET_KEY)");
test.setTimeout(240_000);

const API = process.env.E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

test("quick-add, import, share, calendar, leftovers and templates", async ({
  page,
  browser,
  context,
}) => {
  // The phone's share sheet would wait for a person: copy the link instead.
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "share", { value: undefined });
  });
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);

  const clerkClient = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY });
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;
  const email = `e2e+clerk_test+features${stamp}@example.com`;
  const user = await clerkClient.users.createUser({
    emailAddress: [email],
    password: `Larder-e2e-${stamp}-${crypto.randomUUID()}`,
  });
  try {
    await page.goto("/");
    await setupClerkTestingToken({ page });
    await clerk.signIn({ page, emailAddress: email });
    await api(page, "PUT", "/me/region", {
      country: "IE",
      timezone: "Europe/Dublin",
      locale: "en-IE",
    });
    await api(page, "PUT", "/me/goals", {
      goal: "maintain",
      kcal_min: 1800,
      kcal_max: 2400,
      calorie_floor: 1200,
      max_daily_deficit: 1000,
      currency: "EUR",
    });
    await api(page, "PUT", "/me/allergies", { allergens: ["peanuts"], avoid_food_ids: [] });
    await api(page, "PUT", "/me/preferences", {});
    const plan = await api(page, "POST", "/plans", {});

    await test.step("quick-add food to the diary", async () => {
      await page.goto("/diary");
      await page.getByRole("button", { name: "Add food" }).click();
      await page.getByLabel("Search foods, e.g. banana").fill("banana");
      await page
        .getByRole("button", { name: /Bananas, raw/i })
        .first()
        .click();
      // A snack, whatever the time: the meal defaults to the time of day, and logging over
      // today's dinner would take the dinner the leftovers step below cooks extra of.
      await page.getByLabel("Meal", { exact: true }).selectOption("snack");
      const logged = page.waitForResponse((r) => r.url().endsWith("/diary/log"));
      await page.getByRole("button", { name: "Log it" }).click();
      expect((await logged).ok()).toBe(true);
      const diary = await api(page, "GET", "/diary?days=1");
      expect(JSON.stringify(diary)).toMatch(/banana/i);
    });

    await test.step("type a recipe in and save it", async () => {
      await page.goto("/recipes/import");
      await page.getByRole("button", { name: "Type a recipe in instead" }).click();
      await page.getByLabel("Name").fill("Weeknight chicken and rice");
      await page.getByRole("button", { name: "Add ingredient" }).click();
      const lines = [
        ["300 g", "chicken breast"],
        ["150 g", "rice"],
        ["200 g", "broccoli"],
      ];
      for (const [i, [amount, name]] of lines.entries()) {
        await page.getByRole("textbox", { name: `Amount ${i + 1}`, exact: true }).fill(amount!);
        await page.getByRole("textbox", { name: `Ingredient ${i + 1}`, exact: true }).fill(name!);
      }
      await page.getByLabel("Method").fill("Cook the rice. Fry the chicken. Steam the broccoli.");
      await page.getByRole("button", { name: "Save recipe" }).click();
      await expect(page).toHaveURL(/\/recipes\/\d+$/, { timeout: 30_000 });
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        "Weeknight chicken and rice",
      );
    });

    await test.step("rate it, note it, then edit it", async () => {
      const rated = page.waitForResponse((r) => r.url().endsWith("/note"));
      await page.getByRole("radio", { name: "4 stars" }).click();
      expect((await rated).ok()).toBe(true);
      await page.getByRole("textbox", { name: "Note" }).fill("Less rice next time");
      await page.getByRole("button", { name: "Save note" }).click();
      await expect(page.getByRole("button", { name: "Save note" })).toHaveCount(0);

      await page.getByRole("link", { name: "Edit", exact: true }).click();
      await page.getByRole("textbox", { name: "Name" }).fill("Weeknight chicken and broccoli");
      await page.getByRole("button", { name: "Save changes" }).click();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        "Weeknight chicken and broccoli",
        { timeout: 30_000 },
      );
      await expect(page.getByRole("textbox", { name: "Note" })).toHaveValue("Less rice next time");
    });

    await test.step("share it, see it signed out, then stop sharing", async () => {
      const made = page.waitForResponse(
        (r) => r.url().endsWith("/share") && r.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Share" }).first().click();
      const { path } = await (await made).json();
      const visitor = await browser.newContext();
      const open = await visitor.newPage();
      const shown = await open.goto(new URL(path, page.url()).toString());
      expect(shown?.status()).toBe(200);
      await expect(open.getByRole("heading", { level: 1 })).toHaveText(
        "Weeknight chicken and broccoli",
      );
      // The recipe's own allergen facts are shown; nothing about the person (their pantry,
      // their allergies: this account avoids peanuts) is.
      await expect(open.getByText(/in your pantry|planned without|peanut/i)).toHaveCount(0);

      const revoked = page.waitForResponse(
        (r) => r.request().method() === "DELETE" && r.url().includes("/share/"),
      );
      await page.getByRole("button", { name: "Stop sharing" }).click();
      expect((await revoked).status()).toBe(204);
      // The page streams, so a revoked link answers 200 with the not-found page (and noindex).
      await open.goto(new URL(path, page.url()).toString());
      await expect(open.getByRole("heading", { name: "Page not found" })).toBeVisible();
      expect(
        (await page.request.get(`${API}/public${path.replace(/^\/s\//, "/share/")}`)).status(),
      ).toBe(404);
      await visitor.close();
    });

    await test.step("shop together: tick the list signed out, the owner sees it", async () => {
      await page.goto("/plan/shopping");
      const made = page.waitForResponse(
        (r) => r.url().endsWith("/share") && r.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Shop together" }).click();
      const { path } = await (await made).json();
      const visitor = await browser.newContext();
      const open = await visitor.newPage();
      await open.goto(new URL(path, page.url()).toString());
      await expect(open.getByRole("heading", { level: 1 })).toHaveText("Shopping list");
      await expect(open.getByText(/£|€|\$/)).toHaveCount(0); // no prices
      const row = open.getByRole("listitem").first();
      const name = (await row.locator("label").innerText()).trim();
      const saved = open.waitForResponse(
        (r) => r.request().method() === "PATCH" && r.url().includes("/public/share/"),
      );
      await row.getByRole("checkbox").click();
      expect((await saved).ok()).toBe(true);
      await expect(row.getByRole("checkbox")).toBeChecked();

      await page.reload();
      await expect(page.getByRole("checkbox", { name, exact: true }).first()).toBeChecked();
      await page.getByRole("button", { name: "Shop together" }).click();
      const revoked = page.waitForResponse(
        (r) => r.request().method() === "DELETE" && r.url().includes("/share/"),
      );
      await page.getByRole("button", { name: "Stop sharing" }).click();
      expect((await revoked).status()).toBe(204);
      await visitor.close();
    });

    await test.step("calendar feed", async () => {
      await page.goto("/profile");
      const turnedOn = page.waitForResponse(
        (r) => r.url().endsWith("/me/calendar") && r.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Add to my calendar" }).click();
      const { path } = await (await turnedOn).json();
      const feed = await page.request.get(`${API}${path}`); // no sign-in: the token is the permission
      expect(feed.ok()).toBe(true);
      const text = await feed.text();
      expect(text).toContain("BEGIN:VCALENDAR");
      expect(text).toContain("BEGIN:VEVENT");
    });

    await test.step("cook extra tonight for tomorrow's lunch", async () => {
      expect(plan.days.length).toBeGreaterThan(1);
      await page.goto("/plan");
      const today = page.getByRole("list", { name: /^Meals on / }).first();
      await today.getByRole("button", { name: "Dinner options" }).click();
      const replanned = page.waitForResponse((r) => r.url().endsWith("/plans/replan"));
      await page.getByRole("button", { name: "Cook extra for tomorrow's lunch" }).click();
      expect((await replanned).ok()).toBe(true);
      await expect(page.getByText("Cook extra: it's tomorrow's lunch too")).toBeVisible();
      await page.getByRole("tablist", { name: "Day" }).getByRole("tab").nth(1).click();
      await expect(page.getByText("Leftovers from last night's dinner")).toBeVisible();
    });

    await test.step("save the week as a template and plan from it", async () => {
      await page.goto("/plan");
      await page.getByRole("button", { name: "Save as template" }).click();
      await page.getByLabel("Template name").fill("Busy weeknights");
      const saved = page.waitForResponse((r) => r.url().endsWith("/me/templates"));
      await page.getByRole("button", { name: "Save", exact: true }).click();
      expect((await saved).status()).toBe(201);

      await page.getByRole("button", { name: "New plan" }).click();
      const planned = page.waitForResponse(
        (r) => r.url().endsWith("/plans") && r.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Use template" }).click();
      expect((await planned).status()).toBe(201);
      await expect(page.getByRole("group", { name: "Confirm new plan" })).toHaveCount(0);
    });

    await test.step("meal prep from the plan", async () => {
      await page.goto("/plan");
      await page.getByRole("button", { name: "Meal prep" }).click();
      const boxes = page.getByRole("group", { name: /Cook ahead/ }).getByRole("checkbox");
      await boxes.nth(0).check();
      await boxes.nth(1).check();
      await page.getByRole("button", { name: "Start meal prep" }).click();
      await expect(page).toHaveURL(/\/prep\?r=\d+x[\d.]+,\d+x[\d.]+/);
      await expect(page.getByRole("heading", { name: "Meal prep" })).toBeVisible();
      await expect(
        page.getByRole("region", { name: "Steps" }).getByRole("listitem").first(),
      ).toBeVisible();
      await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0); // no tab bar
    });

    await test.step("copy another day's meals", async () => {
      await page.goto("/plan");
      await page.getByRole("tablist", { name: "Day" }).getByRole("tab").nth(2).click();
      await page.getByRole("button", { name: "Copy another day" }).first().click();
      const from = page.getByLabel("Use the meals from");
      // Two days later this week has meals planned too.
      const target = await page.evaluate(() => {
        const d = new Date();
        d.setDate(d.getDate() + 4);
        return d.toLocaleDateString("en-CA");
      });
      await from.fill(target);
      const replanned = page.waitForResponse((r) => r.url().endsWith("/plans/replan"));
      await page.getByRole("button", { name: "Use these meals" }).click();
      expect((await replanned).ok()).toBe(true);
    });

    await api(page, "DELETE", "/me");
  } finally {
    await clerkClient.users.deleteUser(user.id).catch(() => undefined);
  }
});
