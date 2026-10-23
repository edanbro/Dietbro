import { describe, expect, it } from "vitest";

import { foodName, pantryUse, stillNeeded } from "./food-name";

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

describe("pantryUse", () => {
  it("names pantry foods readably, each once", () => {
    expect(pantryUse(["Egg, whole, raw, fresh"])).toBe("Uses your egg");
    expect(pantryUse(["Carrots, raw", "Onions, raw"])).toBe("Uses your carrots and onions");
    expect(pantryUse(["Carrots, raw", "Carrots, baby, raw", "Onions, raw"])).toBe(
      "Uses your carrots and onions",
    );
    expect(pantryUse(["Carrots, raw", "Onions, raw", "Rice, white, long-grain", "Leeks"])).toBe(
      "Uses your carrots, onions +2",
    );
  });
});

describe("stillNeeded", () => {
  it("names what a recipe still needs, or says there's nothing to get", () => {
    expect(stillNeeded([])).toBe("Nothing else to get");
    expect(stillNeeded(["Carrots, raw"])).toBe("Need carrots");
    expect(stillNeeded(["Carrots, raw", "Onions, raw"])).toBe("Need carrots and onions");
    expect(stillNeeded(["Carrots, raw", "Onions, raw", "Garlic, raw", "Leeks, raw"])).toBe(
      "Need carrots, onions +2",
    );
  });
});
