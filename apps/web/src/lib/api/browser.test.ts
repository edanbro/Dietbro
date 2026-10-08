import { describe, expect, it } from "vitest";

import { ApiError, errorMessages, unwrap } from "./browser";

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
