import { describe, expect, it } from "vitest";

import { ChangeProblemError, isChangeProblem } from "./problems";

describe("isChangeProblem", () => {
  it("recognises the replan refusals by their code", () => {
    expect(isChangeProblem({ code: "busy", detail: ["Still working"] })).toBe(true);
    expect(isChangeProblem({ code: "duplicate", detail: [] })).toBe(true);
    expect(isChangeProblem({ code: "nope", detail: [] })).toBe(false);
    expect(isChangeProblem({ detail: ["Not found"] })).toBe(false);
    expect(isChangeProblem(undefined)).toBe(false);
  });

  it("keeps the code on the error", () => {
    const error = new ChangeProblemError(409, { code: "busy", detail: ["Still working"] });
    expect([error.status, error.code, error.message]).toEqual([409, "busy", "Still working"]);
  });
});
