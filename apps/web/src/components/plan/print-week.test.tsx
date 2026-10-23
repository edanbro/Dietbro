import { act, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makePlan } from "@/test/fixtures";

import { PrintWeek } from "./print-week";

const print = (event: "beforeprint" | "afterprint") =>
  act(() => {
    window.dispatchEvent(new Event(event));
  });

describe("PrintWeek", () => {
  it("is there only while printing: the week as a table, a row a day", () => {
    render(<PrintWeek plan={makePlan()} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    print("beforeprint");

    expect(
      screen.getByRole("heading", { name: "Meals for Fri 9 Oct – Thu 15 Oct" }),
    ).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["Day", "Breakfast", "Lunch", "Dinner"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(7);
    expect(rows[0]).toHaveTextContent("Fri 9");
    expect(rows[0]).toHaveTextContent("Breakfast 1×1½ · 600 kcal");

    print("afterprint");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says who to cook for when the plan is for a household", () => {
    render(<PrintWeek plan={makePlan({ household: 4 })} />);
    print("beforeprint");

    expect(screen.getByText("Servings are each person's; cook for 4.")).toBeInTheDocument();
    print("afterprint");
  });
});
