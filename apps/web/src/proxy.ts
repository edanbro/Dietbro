import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Signed-out visitors to app pages are sent to sign-in. The API independently verifies the
// session token on every request, so this is a UX redirect, not the security boundary.
const isAppRoute = createRouteMatcher([
  "/plan(.*)",
  "/chat(.*)",
  "/setup(.*)",
  "/pantry(.*)",
  "/profile(.*)",
]);

export default clerkMiddleware(
  async (auth, request) => {
    if (isAppRoute(request)) await auth.protect();
  },
  {
    signInUrl: "/sign-in",
    signUpUrl: "/sign-up",
    // Serve Clerk's traffic from our own origin (/__clerk) instead of *.clerk.accounts.dev,
    // so ad and tracker blockers can't break sign-in or the session token refresh.
    frontendApiProxy: { enabled: true },
  },
);

export const config = {
  matcher: [
    // Everything except Next internals and static files.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // The Clerk proxy, including its script files.
    "/__clerk/(.*)",
  ],
};
