import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Signed-out visitors to app pages are sent to sign-in. The API independently verifies the
// session token on every request, so this is a UX redirect, not the security boundary.
const isAppRoute = createRouteMatcher([
  "/plan(.*)",
  "/setup(.*)",
  "/pantry(.*)",
  "/profile(.*)",
]);

export default clerkMiddleware(
  async (auth, request) => {
    if (isAppRoute(request)) await auth.protect();
  },
  { signInUrl: "/sign-in", signUpUrl: "/sign-up" },
);

export const config = {
  matcher: [
    // Everything except Next internals and static files.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
  ],
};
