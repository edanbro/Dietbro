import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, AUTH_UNREACHABLE, errorMessages, sessionToken, unwrap } from "./browser";

describe("errorMessages", () => {
  it("handles FastAPI's three error shapes", () => {
    expect(errorMessages({ detail: "not signed in" })).toEqual(["not signed in"]);
    expect(errorMessages({ detail: ["floor too low", "min above max"] })).toEqual([
      "floor too low",
      "min above max",
    ]);
    expect(
      errorMessages({ detail: [{ loc: ["body", "kcal_min"], msg: "must be ≥ 0" }] }),
    ).toEqual(["kcal_min: must be ≥ 0"]);
    expect(errorMessages(undefined)).toEqual([]);
  });
});

describe("unwrap", () => {
  it("returns data on success", () => {
    expect(unwrap({ data: 1, response: new Response(null, { status: 200 }) })).toBe(1);
  });

  it("throws ApiError with status and messages", () => {
    const fail = () =>
      unwrap({ error: { detail: ["nope"] }, response: new Response(null, { status: 400 }) });
    expect(fail).toThrow(ApiError);
    try {
      fail();
    } catch (e) {
      expect((e as ApiError).status).toBe(400);
      expect((e as ApiError).messages).toEqual(["nope"]);
    }
  });
});

describe("sessionToken", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the token straight away when there is one", async () => {
    await expect(sessionToken(async () => "tok")).resolves.toBe("tok");
  });

  it("fails with a readable error instead of hanging when Clerk can't be reached", async () => {
    vi.useFakeTimers();
    const result = sessionToken(() => new Promise(() => {}), { timeoutMs: 1_000 });
    const check = expect(result).rejects.toEqual(new ApiError(0, [AUTH_UNREACHABLE]));
    await vi.advanceTimersByTimeAsync(1_000);
    await check;
  });

  it("waits for a session that is still being set up right after sign-in", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const getToken = vi.fn(async () => (++calls < 3 ? null : "tok"));
    const result = sessionToken(getToken, { graceMs: 1_000, pollMs: 100 });
    await vi.advanceTimersByTimeAsync(200);
    await expect(result).resolves.toBe("tok");
    expect(getToken).toHaveBeenCalledTimes(3);
  });

  it("gives up waiting and sends no token when signed out", async () => {
    vi.useFakeTimers();
    const result = sessionToken(async () => null, { graceMs: 500, pollMs: 100 });
    await vi.advanceTimersByTimeAsync(600);
    await expect(result).resolves.toBeNull();
  });
});
