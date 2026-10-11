import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeOutcome } from "@/test/fixtures";

import { changeText, loggedText, mealName, OutcomeCard, RecipeAttachment } from "./outcome-card";

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

describe("OutcomeCard", () => {
  it("shows results, meal changes, logged food and a link to the day in the plan", () => {
    render(<OutcomeCard outcome={makeOutcome()} today={TODAY} />);

    const card = screen.getByRole("article", { name: "Plan updated" });
    expect(within(card).getByRole("list", { name: "Requests" })).toHaveTextContent(
      "Done: Skipped tonight's dinner.",
    );
    expect(
      within(within(card).getByRole("list", { name: "Meal changes" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Today's dinner: Dinner 1 → no meal", "Sat lunch: Lunch 2 (1 → 1½ servings)"]);
    expect(within(card).getByRole("list", { name: "Logged food" })).toHaveTextContent(
      "Skipped today's dinner",
    );
    expect(within(card).getByRole("link", { name: "See plan" })).toHaveAttribute(
      "href",
      "/plan?day=2026-10-09",
    );
  });

  it("says what failed, which days are off target, warnings and notes", () => {
    render(
      <OutcomeCard
        outcome={makeOutcome({
          plan_id: null,
          version: null,
          fresh: false,
          results: [
            {
              index: 0,
              intent: "craving",
              date: "2026-10-09",
              slot: "dinner",
              status: "failed",
              message: "No satay I can plan fits your peanut allergy.",
            },
            {
              index: 1,
              intent: "ate_off_plan",
              date: "2026-10-09",
              slot: "lunch",
              status: "applied",
              message: "Logged your pizza.",
            },
          ],
          changes: [],
          logged: [
            {
              date: "2026-10-09",
              slot: "lunch",
              kind: "off_plan",
              description: "pizza",
              kcal: 850,
              estimated: true,
            },
          ],
          days: [
            {
              date: "2026-10-09",
              kcal: 2600,
              min: 1800,
              max: 2200,
              floor: 1200,
              relaxed: true,
              within: false,
            },
            {
              date: "2026-10-10",
              kcal: 2000,
              min: 1800,
              max: 2200,
              floor: 1200,
              relaxed: false,
              within: true,
            },
          ],
          warnings: ["Tue is over your budget."],
          notes: ["I took that as lunch."],
        })}
        today={TODAY}
      />,
    );

    const card = screen.getByRole("article", { name: "Logged" });
    const requests = within(card).getAllByRole("listitem").slice(0, 2);
    expect(requests[0]).toHaveTextContent("Not done: No satay I can plan fits your peanut allergy.");
    expect(requests[0].className).toContain("destructive");
    expect(card).toHaveTextContent("Pizza – today's lunch, ~850 kcal (estimate)");
    expect(card).toHaveTextContent("Today is now ~2,600 kcal, above your 1,800–2,200 kcal range.");
    expect(card).not.toHaveTextContent("Sat is now");
    expect(within(card).getByRole("list", { name: "Warnings" })).toHaveTextContent(
      "Tue is over your budget.",
    );
    expect(card).toHaveTextContent("I took that as lunch.");
    expect(within(card).getByRole("link", { name: "See plan" })).toBeInTheDocument();
  });

  it("offers no plan link when nothing was saved or logged", () => {
    render(
      <OutcomeCard
        outcome={makeOutcome({
          plan_id: null,
          changes: [],
          logged: [],
          fresh: false,
          results: [
            {
              index: 0,
              intent: "swap",
              date: "2026-10-12",
              slot: "lunch",
              status: "unchanged",
              message: "Monday lunch is already Ramen.",
            },
          ],
        })}
        today={TODAY}
      />,
    );

    const card = screen.getByRole("article", { name: "Plan unchanged" });
    expect(card).toHaveTextContent("Already done: Monday lunch is already Ramen.");
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
  });

  it("says when it started a fresh week", () => {
    render(<OutcomeCard outcome={makeOutcome({ fresh: true })} today={TODAY} />);
    expect(screen.getByRole("article")).toHaveTextContent("I made a new plan for this week first.");
  });
});

describe("RecipeAttachment", () => {
  it("links to the new recipe", () => {
    render(<RecipeAttachment recipeId={4021} name="Smoky bean chilli" />);
    expect(screen.getByRole("link", { name: /New recipe\s*Smoky bean chilli/ })).toHaveAttribute(
      "href",
      "/recipes/4021",
    );
  });
});
