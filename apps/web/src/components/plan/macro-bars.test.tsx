import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DayMacros, MacroBar, MoreNutrients } from "./macro-bars";
import { LABEL_RI } from "@/components/nutrients/micronutrients";

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
    const plain = within(section).getByLabelText("Macros without a target");
    expect(within(plain).getByText("Fat")).toBeInTheDocument();
    expect(within(plain).getByText("Carbs")).toBeInTheDocument();
    expect(within(plain).getByText("230 g")).toBeInTheDocument();
  });
});

describe("MoreNutrients", () => {
  const reference = { fiber_g: 30, sugars_g: 90, sat_fat_g: 20, salt_g: 6, ...LABEL_RI };

  it("shows each against its daily guide and marks misses", () => {
    render(
      <MoreNutrients
        values={{ fiber_g: 21.5, sugars_g: 40, sat_fat_g: 24.2, salt_g: null }}
        reference={reference}
      />,
    );

    const fibre = screen.getByText("21.5 g");
    expect(fibre.className).toMatch(/amber/); // below the fibre guide
    expect(screen.getByText("40.0 g").className).not.toMatch(/amber/);
    expect(screen.getByText("24.2 g").className).toMatch(/amber/); // above the sat fat guide
    expect(screen.getByText("–")).toBeInTheDocument(); // salt unknown
    expect(screen.getByText("aim ≥ 30 g")).toBeInTheDocument();
  });

  it("is hidden when nothing is known", () => {
    const { container } = render(
      <MoreNutrients values={{ fiber_g: null, sugars_g: null, sat_fat_g: null, salt_g: null }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
