import { describe, expect, it } from "vitest";

import {
  bodyWeight,
  cmFrom,
  feetInches,
  formatBodyWeight,
  formatWeight,
  kgFrom,
  perWeight,
} from "./units";

describe("formatWeight", () => {
  it("is grams and kilograms in metric", () => {
    expect(formatWeight(250, "metric")).toBe("250 g");
    expect(formatWeight(1200, "metric")).toBe("1.2 kg");
  });

  it("is ounces under a pound and pounds above in US units", () => {
    expect(formatWeight(2, "us")).toBe("0.1 oz");
    expect(formatWeight(250, "us")).toBe("9 oz");
    expect(formatWeight(453.6, "us")).toBe("1 lb");
    expect(formatWeight(1200, "us")).toBe("2.6 lb");
    expect(formatWeight(100_000, "us")).toBe("220 lb");
  });
});

describe("body weight", () => {
  it("shows kilograms or pounds, and reads them back as kilograms", () => {
    expect(formatBodyWeight(72.4, "metric")).toBe("72.4 kg");
    expect(formatBodyWeight(72.4, "us")).toBe("159.6 lb");
    expect(bodyWeight(80, "us")).toBe(176.4);
    expect(kgFrom(160, "us")).toBe(72.6);
    expect(kgFrom(72.4, "metric")).toBe(72.4);
  });
});

describe("height", () => {
  it("converts centimetres to feet and inches and back", () => {
    expect(feetInches(178)).toEqual([5, 10]);
    expect(feetInches(152.4)).toEqual([5, 0]);
    expect(cmFrom(5, 10)).toBe(177.8);
  });
});

describe("perWeight", () => {
  it("prices per kg, or per lb in US units", () => {
    expect(perWeight(1000, "metric")).toEqual({ minor: 1000, unit: "kg" });
    expect(perWeight(1000, "us")).toEqual({ minor: 454, unit: "lb" });
  });
});
