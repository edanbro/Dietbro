import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makePlan } from "@/test/fixtures";

import { Micronutrients, WeekMicronutrients } from "./micronutrients";

describe("Micronutrients", () => {
  it("shows amounts against the label reference intakes, and says when data is missing", () => {
    render(
      <Micronutrients
        values={{ iron_mg: 3.5, vitamin_c_mg: 40, vitamin_d_ug: null }}
        mode="serving"
      />,
    );
    const list = within(screen.getByRole("list", { name: "Vitamins and minerals" }));
    expect(list.getByText("Iron").parentElement).toHaveTextContent("3.5 mg · 25%");
    expect(list.getByText("Vitamin C").parentElement).toHaveTextContent("40 mg · 50%");
    expect(list.getByText("Vitamin D").parentElement).toHaveTextContent("no data");
    expect(screen.queryByText(/low/)).not.toBeInTheDocument(); // a serving isn't a day
  });

  it("marks a day under half the reference intake", () => {
    render(<Micronutrients values={{ iron_mg: 5, calcium_mg: 900 }} mode="day" />);
    expect(screen.getByText("Iron").parentElement).toHaveTextContent("36% (low)");
    expect(screen.getByText("Calcium").parentElement).toHaveTextContent("113%");
    expect(screen.getByText("Calcium").parentElement).not.toHaveTextContent("low");
  });

  it("shows nothing when nothing is known", () => {
    const { container } = render(<Micronutrients values={{ iron_mg: null }} mode="day" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("WeekMicronutrients", () => {
  it("averages the week over its days", () => {
    const plan = makePlan();
    plan.week_totals = { ...plan.week_totals, iron_mg: 70, vitamin_b12_ug: null };
    render(<WeekMicronutrients plan={plan} />);
    expect(screen.getByRole("heading", { name: "Vitamins and minerals" })).toBeInTheDocument();
    expect(screen.getByText("Iron").parentElement).toHaveTextContent("10 mg · 71%"); // 70 / 7 days
    expect(screen.getByText("Vitamin B12").parentElement).toHaveTextContent("no data");
  });
});
