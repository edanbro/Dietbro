import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const createSignInToken = vi.fn(async () => ({ token: "ticket-123" }));
vi.mock("@clerk/nextjs/server", () => ({
  clerkClient: async () => ({ signInTokens: { createSignInToken } }),
}));

import { POST } from "./route";

const post = (ip = "1.2.3.4") =>
  POST(new Request("http://x/api/demo", { method: "POST", headers: { "x-forwarded-for": ip } }));

beforeEach(() => vi.stubEnv("DEMO_CLERK_USER_ID", "user_demo"));
afterEach(() => {
  vi.unstubAllEnvs();
  createSignInToken.mockClear();
});

describe("POST /api/demo", () => {
  it("mints a short ticket for the demo user", async () => {
    const response = await post();
    expect(await response.json()).toEqual({ ticket: "ticket-123" });
    expect(createSignInToken).toHaveBeenCalledWith({ userId: "user_demo", expiresInSeconds: 120 });
  });

  it("is off without a demo user", async () => {
    vi.stubEnv("DEMO_CLERK_USER_ID", "");
    expect((await post()).status).toBe(404);
  });

  it("limits tickets per address", async () => {
    const codes: number[] = [];
    for (let i = 0; i < 21; i++) codes.push((await post("9.9.9.9")).status);
    expect(codes.slice(0, 20).every((c) => c === 200)).toBe(true);
    expect(codes[20]).toBe(429);
  });
});
