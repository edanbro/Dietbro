import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { daysUntil, ExpiryBadge, formatAmount } from "./pantry-list";

const TODAY = new Date(2026, 9, 8); // 8 Oct 2026, local time

describe("daysUntil", () => {
  it("counts whole calendar days", () => {
    expect(daysUntil("2026-10-08", TODAY)).toBe(0);
    expect(daysUntil("2026-10-11", TODAY)).toBe(3);
    expect(daysUntil("2026-10-01", TODAY)).toBe(-7);
  });
});

describe("ExpiryBadge", () => {
  it.each([
    ["2026-10-01", "Expired"],
    ["2026-10-08", "Use today"],
    ["2026-10-09", "1 day"],
    ["2026-10-10", "2 days"],
    ["2026-11-01", "by 2026-11-01"],
  ])("%s -> %s", (date, text) => {
    render(<ExpiryBadge date={date} today={TODAY} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("renders nothing without a date", () => {
    const { container } = render(<ExpiryBadge date={null} today={TODAY} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("formatAmount", () => {
  it("shows the entered unit and grams", () => {
    expect(formatAmount({ quantity: 2, unit: "large", grams: 300, approx: false })).toBe(
      "2 large · 300 g",
    );
    expect(formatAmount({ quantity: 0.5, unit: "kg", grams: 500, approx: true })).toBe(
      "~0.5 kg · 500 g",
    );
    expect(formatAmount({ quantity: 250, unit: "g", grams: 250, approx: false })).toBe("250 g");
  });
});
