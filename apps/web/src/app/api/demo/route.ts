import { clerkClient } from "@clerk/nextjs/server";

/**
 * "Try the demo": a two-minute, one-use sign-in ticket for the shared demo user, minted with
 * the server's Clerk secret key (the browser never sees a password). Off unless
 * DEMO_CLERK_USER_ID is set. A small per-address limit keeps tickets from being farmed.
 */

const WINDOW_MS = 60 * 60 * 1000;
const PER_WINDOW = 20;
const recent = new Map<string, number[]>();

function allowed(key: string, now: number): boolean {
  const hits = (recent.get(key) ?? []).filter((t) => now - t < WINDOW_MS);
  if (hits.length >= PER_WINDOW) {
    recent.set(key, hits);
    return false;
  }
  recent.set(key, [...hits, now]);
  if (recent.size > 10_000) recent.clear(); // bounded memory; the limit is best-effort
  return true;
}

export async function POST(request: Request): Promise<Response> {
  const userId = process.env.DEMO_CLERK_USER_ID;
  if (!userId) return Response.json({ detail: ["The demo isn't set up here."] }, { status: 404 });
  const ip = (request.headers.get("x-forwarded-for") ?? "").split(",")[0]?.trim() || "unknown";
  if (!allowed(ip, Date.now())) {
    return Response.json({ detail: ["Too many demo sign-ins. Try again later."] }, { status: 429 });
  }
  try {
    const client = await clerkClient();
    const token = await client.signInTokens.createSignInToken({ userId, expiresInSeconds: 120 });
    return Response.json({ ticket: token.token }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ detail: ["The demo is unavailable right now."] }, { status: 503 });
  }
}
