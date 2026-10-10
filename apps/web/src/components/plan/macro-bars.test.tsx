import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DayMacros, MacroBar } from "./macro-bars";

describe("MacroBar", () => {
  it("shows an in-band value as on target", () => {
    render(
      <MacroBar label="Calories" unit="kcal" value={1950} band={{ min: 1800, max: 2200 }} hard />,
    );
    const meter = screen.getByRole("meter", { name: "Calories" });
    expect(meter).toHaveAttribute("aria-valuenow", "1950");
    expect(meter).toHaveAttribute("aria-valuetext", "1,950 kcal, target 1,800–2,200 kcal");
    expect(meter).toHaveAttribute("data-status", "within");
    expect(screen.getByText("On target")).toBeInTheDocument();
    expect(screen.getByText("Target 1,800–2,200 kcal")).toBeInTheDocument();
  });

  it("marks a hard miss in words and in the destructive colour", () => {
    render(
      <MacroBar label="Calories" unit="kcal" value={1680} band={{ min: 1800, max: 2200 }} hard />,
    );
    const meter = screen.getByRole("meter", { name: "Calories" });
    expect(meter).toHaveAttribute("data-status", "below");
    expect(meter).toHaveAttribute("aria-valuetext", expect.stringContaining("120 kcal under"));
    const verdict = screen.getByText("120 kcal under");
    expect(verdict).toHaveClass("text-destructive");
  });

  it("marks a soft miss as a gentler warning", () => {
    render(<MacroBar label="Fat" unit="g" value={78} band={{ min: null, max: 70 }} />);
    expect(screen.getByRole("meter", { name: "Fat" })).toHaveAttribute("data-status", "above");
    const verdict = screen.getByText("8 g over");
    expect(verdict).not.toHaveClass("text-destructive");
    expect(verdict.className).toContain("amber");
  });

  it("shows only the value when there is no target", () => {
    render(<MacroBar label="Carbs" unit="g" value={230} band={null} />);
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(screen.getByText("230 g")).toBeInTheDocument();
    expect(screen.getByText("No target set")).toBeInTheDocument();
  });
});

describe("DayMacros", () => {
  it("compares the day with the daily bands: kcal hard, macros soft", () => {
    render(
      <DayMacros
        totals={{ kcal: 1750, protein_g: 60, fat_g: 60, carbs_g: 230 }}
        bands={{ kcal: { min: 1800, max: 2200 }, protein_g: { min: 72, max: null } }}
      />,
    );
    const section = screen.getByRole("region", { name: "Day totals" });
    expect(within(section).getAllByRole("meter")).toHaveLength(2);
    expect(within(section).getByText("50 kcal under")).toHaveClass("text-destructive");
    expect(within(section).getByText("12 g under")).not.toHaveClass("text-destructive");
    expect(within(section).getAllByText("No target set")).toHaveLength(2);
  });
});
