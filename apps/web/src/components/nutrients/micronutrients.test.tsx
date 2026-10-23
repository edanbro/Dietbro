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
  it("averages the meals over the days, and says when only some meals have data", () => {
    const plan = makePlan();
    const meals = plan.days.flatMap((d) => d.meals);
    meals.forEach((m, i) => {
      m.nutrition = { ...m.nutrition, iron_mg: 2, vitamin_d_ug: i === 0 ? null : 1 };
    });
    render(<WeekMicronutrients plan={plan} />);
    expect(screen.getByRole("heading", { name: "Vitamins and minerals" })).toBeInTheDocument();
    const perDay = (meals.length * 2) / plan.days.length;
    expect(screen.getByText("Iron").parentElement).toHaveTextContent(`${perDay.toFixed(1)} mg`);
    expect(screen.getByText("Iron").parentElement).not.toHaveTextContent("at least");
    expect(screen.getByText("Vitamin D").parentElement).toHaveTextContent(
      `at least ${((meals.length - 1) / plan.days.length).toFixed(1)} µg`,
    );
    expect(screen.getByText("Vitamin D").parentElement).toHaveTextContent(
      `data for ${meals.length - 1} of ${meals.length} meals`,
    );
    expect(screen.getByText("Vitamin D").parentElement).not.toHaveTextContent("low");
    expect(screen.getByText("Folate").parentElement).toHaveTextContent("no data");
  });
});
