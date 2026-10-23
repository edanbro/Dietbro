import { describe, expect, it } from "vitest";

import { foodName } from "./food-name";

describe("foodName", () => {
  it.each([
    ["Peppers, sweet, red, raw", "Sweet red peppers", null],
    ["Spices, ginger, ground", "Ground ginger", null],
    ["Fish, haddock, smoked", "Smoked haddock", null],
    ["Oil, olive, salad or cooking", "Olive oil", null],
    ["Salad dressing, mayonnaise, regular", "Mayonnaise", null],
    ["Sugars, granulated", "Granulated sugar", null],
    ["Tomatoes, red, ripe, raw, year round average", "Red tomatoes", null],
    ["Bread, whole-wheat, commercially prepared", "Whole-wheat bread", null],
    ["Thyme, fresh", "Fresh thyme", null],
    [
      "Raisins, dark, seedless (Includes foods for USDA's Food Distribution Program)",
      "Dark raisins",
      "seedless",
    ],
    ["Salt, table", "Salt", null],
    ["Wheat flour, white, all-purpose, enriched, unbleached", "White wheat flour", "all-purpose"],
    [
      "Chicken, broiler or fryers, breast, skinless, boneless, meat only, raw",
      "Chicken",
      "breast, skinless, boneless",
    ],
    [
      'Beef, chuck, arm pot roast, separable lean only, trimmed to 1/8" fat, choice, raw',
      "Beef",
      "chuck, arm pot roast",
    ],
  ])("%s", (description, name, detail) => {
    expect(foodName(description)).toEqual({ name, detail });
  });

  it("leaves product names alone", () => {
    expect(foodName("Kerrygold Pure Irish Butter")).toEqual({
      name: "Kerrygold Pure Irish Butter",
      detail: null,
    });
  });
});
