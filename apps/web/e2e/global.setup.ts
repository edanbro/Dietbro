import { clerkSetup } from "@clerk/testing/playwright";
import { test as setup } from "@playwright/test";

setup.describe.configure({ mode: "serial" });

setup("clerk testing token", async () => {
  setup.skip(!process.env.CLERK_SECRET_KEY, "needs a Clerk dev instance (CLERK_SECRET_KEY)");
  // Fetches a testing token so Clerk's bot protection lets Playwright through.
  await clerkSetup();
});
