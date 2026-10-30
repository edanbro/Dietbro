import { describe, expect, it } from "vitest";

import { changeText, loggedText, mealName } from "./outcome-text";

const TODAY = "2026-10-09"; // a Friday

describe("wording", () => {
  it("names meals relative to today", () => {
    expect(mealName("2026-10-09", "dinner", TODAY)).toBe("today's dinner");
    expect(mealName("2026-10-15", "dinner", TODAY)).toBe("Thu dinner");
    expect(mealName("2026-10-22", "lunch", TODAY)).toBe("Thu 22 Oct lunch");
    expect(mealName("2026-10-08", null, TODAY)).toBe("Thu");
  });

  it("describes swaps, skips and size changes", () => {
    const thu = { date: "2026-10-15", slot: "dinner" as const, reason: "swap" as const };
    expect(changeText({ ...thu, before: "Lasagne", after: "Chilli con carne" }, TODAY)).toBe(
      "Thu dinner: Lasagne → Chilli con carne",
    );
    expect(changeText({ ...thu, before: "Lasagne", after: null }, TODAY)).toBe(
      "Thu dinner: Lasagne → no meal",
    );
    expect(
      changeText(
        { ...thu, before: "Lasagne", after: "Lasagne", before_portions: 2, after_portions: 3 },
        TODAY,
      ),
    ).toBe("Thu dinner: Lasagne (1 → 1½ servings)");
  });

  it("describes logged food with estimates as estimates", () => {
    const base = { date: TODAY, slot: "lunch" as const, estimated: true };
    expect(
      loggedText({ ...base, kind: "off_plan", description: "2 slices of pizza", kcal: 850 }, TODAY),
    ).toBe("2 slices of pizza – today's lunch, ~850 kcal (estimate)");
    expect(
      loggedText(
        { ...base, kind: "off_plan", description: "latte", kcal: 120, estimated: false },
        TODAY,
      ),
    ).toBe("Latte – today's lunch, 120 kcal");
    expect(loggedText({ ...base, kind: "skipped", description: "", kcal: 0 }, TODAY)).toBe(
      "Skipped today's lunch",
    );
    expect(loggedText({ ...base, kind: "skipped", description: "", kcal: 1650 }, TODAY)).toBe(
      "Skipped today's lunch, ~1,650 kcal counted for eating out",
    );
  });
});
