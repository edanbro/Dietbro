import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PlanOutcome, SlotChange } from "@/lib/api/hooks";

import { changeLine, WhatChanged } from "./what-changed";

vi.mock("next/navigation", () => import("@/test/navigation"));

const TODAY = "2026-10-09"; // a Friday

function change(overrides: Partial<SlotChange>): SlotChange {
  return {
    date: "2026-10-10",
    slot: "dinner",
    before: "Lentil stew",
    after: "Chilli",
    reason: "rebalance",
    ...overrides,
  };
}

describe("changeLine", () => {
  it.each<[Partial<SlotChange>, string]>([
    [{ reason: "skip", after: null }, "Sat dinner: Lentil stew → no meal — you're skipping it"],
    [{ reason: "swap" }, "Sat dinner: Lentil stew → Chilli — swapped as you asked"],
    [{ reason: "craving" }, "Sat dinner: Lentil stew → Chilli — you asked for it"],
    [
      { reason: "ate_off_plan", after: null },
      "Sat dinner: Lentil stew → no meal — you had something else",
    ],
    [
      { reason: "rebalance" },
      "Sat dinner: Lentil stew → Chilli — rebalanced to keep Sat on target",
    ],
    [
      { reason: "rebalance", date: TODAY, slot: "lunch" },
      "Today's lunch: Lentil stew → Chilli — rebalanced to keep today on target",
    ],
    [
      { reason: "resize", after: "Lentil stew", before_portions: 2, after_portions: 4 },
      "Sat dinner: Lentil stew (1 → 2 servings) — portion resized to fit the day",
    ],
  ])("%o", (c, text) => {
    expect(changeLine(change(c), TODAY)).toBe(text);
  });
});

describe("WhatChanged", () => {
  const outcome: PlanOutcome = {
    type: "outcome",
    plan_id: 8,
    version: 3,
    fresh: true,
    results: [
      {
        index: 0,
        intent: "skip",
        date: "2026-10-10",
        slot: "dinner",
        status: "applied",
        message: "Skipped Sat dinner.",
      },
      {
        index: 1,
        intent: "swap",
        date: TODAY,
        slot: "breakfast",
        status: "failed",
        message: "Fri breakfast is already over.",
      },
    ],
    changes: [change({ reason: "skip", after: null }), change({ slot: "lunch" })],
    logged: [],
    days: [
      {
        date: "2026-10-10",
        kcal: 1500,
        min: 1800,
        max: 2200,
        floor: 1200,
        relaxed: false,
        within: false,
      },
    ],
    warnings: ["Sat is light on protein."],
    notes: ["Shopping list updated."],
  };

  it("lists results, meal changes with reasons, day notes, warnings and notes", () => {
    const dismiss = vi.fn();
    render(<WhatChanged outcome={outcome} today={TODAY} onDismiss={dismiss} />);

    const panel = screen.getByRole("region", { name: "What changed" });
    expect(panel).toHaveFocus();
    expect(panel).toHaveTextContent("A new plan for this week was made first.");
    const results = within(panel).getAllByRole("listitem").slice(0, 2);
    expect(results.map((li) => li.textContent)).toEqual([
      "Done: Skipped Sat dinner.",
      "Not done: Fri breakfast is already over.",
    ]);
    expect(within(panel).getByRole("list", { name: "Meal changes" })).toHaveTextContent(
      "Sat lunch: Lentil stew → Chilli — rebalanced to keep Sat on target",
    );
    expect(panel).toHaveTextContent("Sat is now ~1,500 kcal, below your 1,800–2,200 kcal range.");
    expect(within(panel).getByRole("list", { name: "Warnings" })).toHaveTextContent(
      "Sat is light on protein.",
    );
    expect(panel).toHaveTextContent("Shopping list updated.");

    fireEvent.click(within(panel).getByRole("button", { name: "Dismiss" }));
    expect(dismiss).toHaveBeenCalled();
  });

  it("says when the meals stayed as they were", () => {
    render(
      <WhatChanged
        outcome={{ type: "outcome", fresh: false, plan_id: null, results: [], changes: [] }}
        today={TODAY}
        onDismiss={() => undefined}
      />,
    );
    expect(screen.getByRole("region", { name: "What changed" })).toHaveTextContent(
      "Your meals stay as they were.",
    );
  });
});
