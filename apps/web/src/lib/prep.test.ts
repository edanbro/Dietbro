import { describe, expect, it } from "vitest";

import { estimate, fitTo, parsePrep, type PrepRecipe, schedule, totalTime } from "./prep";

describe("estimate", () => {
  it("treats a waiting step with a timer as passive", () => {
    expect(estimate("Simmer for 25 minutes, stirring now and then.")).toMatchObject({
      active: 60,
      passive: 1500,
    });
  });

  it("counts a hands-on timer as active, and guesses the rest from length", () => {
    expect(estimate("Fry the onions for 5 minutes.")).toMatchObject({ active: 300, passive: 0 });
    expect(estimate("Chop the onion.")).toMatchObject({ active: 60, passive: 0, timer: null });
    expect(estimate("word ".repeat(200)).active).toBe(8 * 60); // at most 8 minutes
  });
});

const CHILLI: PrepRecipe = {
  id: 1,
  name: "Chilli",
  steps: ["Brown the mince for 5 minutes.", "Simmer for 40 minutes.", "Season and serve."],
};
const RICE: PrepRecipe = {
  id: 2,
  name: "Rice",
  steps: ["Boil the rice for 12 minutes.", "Drain."],
};
const SALAD: PrepRecipe = {
  id: 3,
  name: "Salad",
  steps: ["Chop the lettuce and tomatoes.", "Dress the salad."],
};

describe("schedule", () => {
  const events = schedule([SALAD, RICE, CHILLI]);

  it("keeps each recipe's steps in order", () => {
    for (const r of [CHILLI, RICE, SALAD]) {
      const mine = events.filter((e) => e.recipeId === r.id);
      expect(mine.map((e) => e.index)).toEqual(r.steps.map((_, i) => i));
      for (let i = 1; i < mine.length; i++) {
        const prev = mine[i - 1]!;
        expect(mine[i]!.start).toBeGreaterThanOrEqual(prev.start + prev.active + prev.passive);
      }
    }
  });

  it("starts the longest recipe first and works on others while it simmers", () => {
    expect(events[0]!.recipe).toBe("Chilli");
    const simmer = events.find((e) => e.step.startsWith("Simmer"))!;
    const during = events.filter(
      (e) => e.recipeId !== CHILLI.id && e.start >= simmer.start && e.start < simmer.start + 2400,
    );
    expect(during.length).toBeGreaterThan(0);
  });

  it("never has the cook doing two things at once", () => {
    for (let i = 1; i < events.length; i++) {
      expect(events[i]!.start).toBeGreaterThanOrEqual(events[i - 1]!.start + events[i - 1]!.active);
    }
  });

  it("takes no longer than cooking them one after another", () => {
    const serial = [CHILLI, RICE, SALAD]
      .flatMap((r) => r.steps.map((s) => estimate(s)))
      .reduce((sum, e) => sum + e.active + e.passive, 0);
    expect(totalTime(events)).toBeLessThan(serial);
    expect(totalTime(events)).toBeGreaterThanOrEqual(300 + 60 + 2400); // the chilli alone
  });
});

describe("fitTo", () => {
  const eggs = ["Whisk the eggs with the milk.", "Stir gently until just set and serve."].map(
    (s) => estimate(s),
  );

  it("stretches untimed steps to the recipe's own time", () => {
    const fitted = fitTo(eggs, 10);
    expect(fitted.reduce((sum, e) => sum + e.active, 0)).toBe(600);
    expect(fitted[0]!.active).toBe(fitted[1]!.active);
  });

  it("leaves timed steps alone, never shrinks, and caps each step", () => {
    const chilli = CHILLI.steps.map((s) => estimate(s));
    expect(fitTo(chilli, 10)).toEqual(chilli);
    expect(fitTo(eggs, null)).toEqual(eggs);
    const long = fitTo(eggs, 600);
    expect(long.every((e) => e.active === 15 * 60)).toBe(true);
  });
});

describe("parsePrep", () => {
  it("reads recipe ids with servings, ignoring the rest", () => {
    expect(parsePrep("12x2,34x1.5,bad,12x3,56x0,78x4,90x2,99x1")).toEqual([
      { id: 12, servings: 2 },
      { id: 34, servings: 1.5 },
      { id: 78, servings: 4 },
      { id: 90, servings: 2 },
    ]);
    expect(parsePrep(null)).toEqual([]);
  });
});
