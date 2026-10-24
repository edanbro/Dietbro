import { describe, expect, it } from "vitest";

import { foodName, foodNoun, pantryUse, stillNeeded } from "./food-name";

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
    ["Alcoholic beverage, wine, table, white", "White wine", null],
    ["Alcoholic beverage, beer, regular, all", "Beer", null],
    ["Alcoholic beverage, distilled, rum, 80 proof", "Rum", "80 proof"],
    ["Beverages, carbonated, tonic water", "Tonic water", null],
    ["Sauce, fish, ready-to-serve", "Fish sauce", null],
    ["Sauce, tomato chili sauce, bottled, with salt", "Tomato chili sauce", "with salt"],
    ["Soup, stock, chicken, home-prepared", "Chicken stock", null],
    ["Soup, vegetable broth, ready to serve", "Vegetable broth", null],
    ["Candies, milk chocolate", "Milk chocolate", null],
    ["Leavening agents, baking soda", "Baking soda", null],
    ["Crustaceans, shrimp, raw", "Shrimp", null],
    [
      "Tomato products, canned, paste, without salt added (Includes foods for USDA's Food Distribution Program)",
      "Canned tomato paste",
      null,
    ],
    ["Bread, crumbs, dry, grated, plain", "Breadcrumbs", "dry, grated, plain"],
    ["Nuts, almonds", "Almonds", null],
    ["Nuts, cashew nuts, raw", "Cashew nuts", null],
    ["Nuts, pine nuts, dried", "Dried pine nuts", null],
    ["Alcoholic beverage, distilled, all (gin, rum, vodka, whiskey) 80 proof", "Spirits", null],
    ["Seeds, sesame seeds, whole, dried", "Sesame seeds", "whole, dried"],
    ["Seeds, sesame butter, tahini", "Sesame butter", "tahini"],
    ["Sugars, powdered", "Powdered sugar", null],
    ["Egg, white, raw, fresh", "Egg white", null],
    ["Chickpeas (garbanzo beans, bengal gram), mature seeds, raw", "Chickpeas (garbanzo beans, bengal gram)", "mature seeds"],
    ["Pork, fresh, shoulder, whole, separable lean only, raw", "Pork", "shoulder, whole"],
    ["Pork, cured, bacon, unprepared", "Bacon", null],
    ["Beef, cured, corned beef, canned", "Canned corned beef", null],
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

describe("foodNoun", () => {
  it("is the food without its adjectives or detail", () => {
    expect(foodNoun("Tomatoes, red, ripe, canned")).toBe("tomatoes");
    expect(foodNoun("Oil, olive, salad or cooking")).toBe("olive oil");
    expect(foodNoun("Spices, paprika")).toBe("paprika");
    expect(foodNoun("Kerrygold Butter")).toBe("kerrygold butter");
  });
});
