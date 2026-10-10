import { describe, expect, it } from "vitest";

import {
  allergenLabel,
  bandStatus,
  formatBand,
  formatGrams,
  formatMoney,
  formatNumber,
  formatServings,
  humanize,
  servingsLabel,
} from "./format";

describe("formatMoney", () => {
  it.each([
    [4210, "GBP", "£42.10"],
    [5, "EUR", "€0.05"],
    [123456, "USD", "$1,234.56"],
  ] as const)("%d %s -> %s", (minor, currency, text) => {
    expect(formatMoney(minor, currency)).toBe(text);
  });
});

describe("formatGrams", () => {
  it.each([
    [0, "0 g"],
    [450, "450 g"],
    [999.6, "1000 g"],
    [1000, "1 kg"],
    [1250, "1.3 kg"],
    [2000, "2 kg"],
  ])("%d -> %s", (grams, text) => {
    expect(formatGrams(grams)).toBe(text);
  });
});

describe("servings", () => {
  it.each([
    [1, "×½", "½ serving"],
    [2, "×1", "1 serving"],
    [3, "×1½", "1½ servings"],
    [4, "×2", "2 servings"],
    [5, "×2½", "2½ servings"],
  ])("%d half-servings -> %s", (portions, short, words) => {
    expect(formatServings(portions)).toBe(short);
    expect(servingsLabel(portions)).toBe(words);
  });
});

describe("bands", () => {
  it("places a value against min, max or both", () => {
    expect(bandStatus(1700, { min: 1800, max: 2200 })).toBe("below");
    expect(bandStatus(1800, { min: 1800, max: 2200 })).toBe("within");
    expect(bandStatus(2200, { min: 1800, max: 2200 })).toBe("within");
    expect(bandStatus(2201, { min: 1800, max: 2200 })).toBe("above");
    expect(bandStatus(50, { min: 72, max: null })).toBe("below");
    expect(bandStatus(500, { min: 72 })).toBe("within");
    expect(bandStatus(80, { max: 70 })).toBe("above");
    expect(bandStatus(80, null)).toBe("none");
    expect(bandStatus(80, { min: null, max: null })).toBe("none");
  });

  it("describes a band", () => {
    expect(formatBand({ min: 1800, max: 2200 }, "kcal")).toBe("1,800–2,200 kcal");
    expect(formatBand({ min: 72, max: null }, "g")).toBe("≥ 72 g");
    expect(formatBand({ max: 70 }, "g")).toBe("≤ 70 g");
    expect(formatBand(undefined, "g")).toBeNull();
  });
});

describe("labels", () => {
  it("humanizes codes and prefers API labels", () => {
    expect(humanize("tree_nuts")).toBe("Tree nuts");
    expect(allergenLabel("tree_nuts")).toBe("Tree nuts");
    expect(allergenLabel("tree_nuts", [{ code: "tree_nuts", label: "Tree nuts (almonds…)" }])).toBe(
      "Tree nuts (almonds…)",
    );
    expect(formatNumber(13300)).toBe("13,300");
  });
});
