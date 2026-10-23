import { describe, expect, it } from "vitest";

import { clock, cookServings, parseServings, scaleFactor, stepTimers } from "./cooking";

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
