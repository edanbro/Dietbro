import { ApiError } from "./browser";
import type { components } from "./schema";

export type ChangeProblem = components["schemas"]["ChangeProblem"];

/** A refused plan change (400 bad_today, 409 busy / duplicate) with its machine-readable code. */
export class ChangeProblemError extends ApiError {
  constructor(
    status: number,
    readonly problem: ChangeProblem,
  ) {
    super(status, problem.detail);
    this.name = "ChangeProblemError";
  }

  get code(): ChangeProblem["code"] {
    return this.problem.code;
  }
}

const PROBLEM_CODES = new Set<string>(["bad_today", "busy", "duplicate"]);

export function isChangeProblem(body: unknown): body is ChangeProblem {
  const b = body as Partial<ChangeProblem> | null | undefined;
  return typeof b?.code === "string" && PROBLEM_CODES.has(b.code) && Array.isArray(b.detail);
}
