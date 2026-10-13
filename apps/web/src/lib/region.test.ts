import { describe, expect, it } from "vitest";

import { currencySymbol, guessRegion } from "./region";

describe("guessRegion", () => {
  it("trusts the time zone over an en-US browser", () => {
    expect(guessRegion("Europe/Dublin", ["en-US", "en"])).toEqual({
      country: "IE",
      timezone: "Europe/Dublin",
      locale: null,
    });
  });

  it("keeps the browser language when it matches the country", () => {
    expect(guessRegion("Europe/Dublin", ["en-IE", "ga"]).locale).toBe("en-IE");
  });

  it("knows US zones but not Canadian ones", () => {
    expect(guessRegion("America/Chicago", ["en-US"]).country).toBe("US");
    expect(guessRegion("America/Indiana/Indianapolis", []).country).toBe("US");
    expect(guessRegion("America/Toronto", ["fr"]).country).toBeNull();
  });

  it("falls back to the language's region, then to asking", () => {
    expect(guessRegion("Etc/UTC", ["en-GB"]).country).toBe("GB");
    expect(guessRegion(null, ["ga"]).country).toBeNull();
  });
});

describe("currencySymbol", () => {
  it("maps the supported currencies", () => {
    expect(currencySymbol("EUR")).toBe("€");
    expect(currencySymbol("GBP")).toBe("£");
    expect(currencySymbol("CHF")).toBe("CHF");
  });
});
