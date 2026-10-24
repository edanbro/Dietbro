import { describe, expect, it } from "vitest";

import {
  clock,
  cookServings,
  parseServings,
  scaledAmount,
  scaleFactor,
  steps,
  stepTimers,
} from "./cooking";

describe("stepTimers", () => {
  it.each([
    ["Simmer for 20 minutes.", [["20 minutes", 1200]]],
    ["Bake 1-2 hours until tender", [["1-2 hours", 7200]]],
    ["Rest 30 to 40 mins", [["30 to 40 mins", 2400]]],
    ["Fry 5 min, then bake for 1.5 hrs", [["5 min", 300], ["1.5 hrs", 5400]]],
    ["Boil ½ hour", [["½ hour", 1800]]],
    ["Roast for 1½ hours", [["1½ hours", 5400]]],
    ["Season to taste.", []],
    ["Cook for 3 days", []],
  ])("%s", (step, expected) => {
    expect(stepTimers(step).map((t) => [t.label, t.seconds])).toEqual(expected);
  });
});

describe("clock", () => {
  it("formats minutes and hours", () => {
    expect(clock(95)).toBe("1:35");
    expect(clock(3725)).toBe("1:02:05");
    expect(clock(-3)).toBe("0:00");
  });
});

describe("scaling", () => {
  it("scales to the servings asked for", () => {
    expect(scaleFactor(3, 2)).toBe(1.5);
    expect(scaleFactor(2, null)).toBe(1);
  });

  it("reads ?servings= in halves", () => {
    expect(parseServings("1.5")).toBe(1.5);
    expect(parseServings("1.3")).toBe(1.5);
    expect(parseServings("0")).toBeNull();
    expect(parseServings("abc")).toBeNull();
    expect(parseServings(null)).toBeNull();
  });

  it("cooks a planned meal for everyone, in halves, up to 20 servings", () => {
    expect(cookServings(1.5)).toBe(1.5);
    expect(cookServings(1.5, 3)).toBe(4.5);
    expect(cookServings(2.5, 8)).toBe(20);
    expect(cookServings(2.5, 7)).toBe(17.5);
  });
});

describe("steps", () => {
  it("drops step headings and numbers", () => {
    expect(steps("STEP 1\r\nChop the onion.\r\n2. Fry it for 5 minutes.\n3) Serve")).toEqual([
      "Chop the onion.",
      "Fry it for 5 minutes.",
      "Serve",
    ]);
  });

  it("joins a line wrapped mid-sentence onto the one before", () => {
    expect(
      steps("Add the eggs and stir\ngently until set.\nServe on toast.\nseason to taste."),
    ).toEqual(["Add the eggs and stir gently until set.", "Serve on toast.", "season to taste."]);
  });
});

describe("scaledAmount in US units", () => {
  it("reads weights in ounces and pounds, and leaves volumes and counts as written", () => {
    expect(scaledAmount({ measure: "50g", grams: 50 }, 1, "us")).toBe("2 oz");
    expect(scaledAmount({ measure: "1 kg", grams: 1000 }, 1, "us")).toBe("2.2 lb");
    expect(scaledAmount({ measure: "250ml", grams: 258 }, 1, "us")).toBe("250ml");
    expect(scaledAmount({ measure: "2 large", grams: 300 }, 1, "us")).toBe("2 large");
    expect(scaledAmount({ measure: "2 large", grams: 300 }, 2, "us")).toBe("1.3 lb");
    expect(scaledAmount({ measure: "50g", grams: 50 }, 1)).toBe("50g");
  });
});
