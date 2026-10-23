import { describe, expect, it } from "vitest";

import { cookExtraFor, leftoverNotes, noteFor } from "./leftovers";

const meal = (slot: string, id: number, status = "planned") => ({ slot, recipe: { id }, status });
const DAYS = [
  { date: "2026-10-20", meals: [meal("lunch", 1), meal("dinner", 7)] },
  { date: "2026-10-21", meals: [meal("lunch", 7), meal("dinner", 8)] },
  { date: "2026-10-22", meals: [meal("lunch", 2, "eaten"), meal("dinner", 9)] },
];

describe("leftovers", () => {
  it("labels a dinner eaten again at the next day's lunch", () => {
    const notes = leftoverNotes(DAYS);
    expect(noteFor(notes, "2026-10-20", "dinner")).toMatch(/tomorrow's lunch/);
    expect(noteFor(notes, "2026-10-21", "lunch")).toMatch(/Leftovers/);
    expect(noteFor(notes, "2026-10-21", "dinner")).toBeUndefined();
  });

  it("offers cooking extra only when tomorrow's lunch can still change", () => {
    expect(cookExtraFor(DAYS, "2026-10-21", "2026-10-20")).toBeNull(); // tomorrow's lunch eaten
    expect(cookExtraFor(DAYS, "2026-10-20", "2026-10-20")).toBeNull(); // already leftovers
    expect(cookExtraFor(DAYS, "2026-10-22", "2026-10-20")).toBeNull(); // last day
    const fresh = [DAYS[0]!, { date: "2026-10-21", meals: [meal("lunch", 3)] }];
    expect(cookExtraFor(fresh, "2026-10-20", "2026-10-20")).toBe("2026-10-21");
    expect(cookExtraFor(fresh, "2026-10-20", "2026-10-21")).toBeNull(); // in the past
  });
});
