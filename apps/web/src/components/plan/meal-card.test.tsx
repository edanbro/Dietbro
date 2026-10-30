import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithClient } from "@/test/api";
import { meal } from "@/test/fixtures";

import { MealCard } from "./meal-card";
import type { MealActionsProps } from "./meal-actions";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

const props = (date: string, onEaten = vi.fn(async () => undefined)) =>
  ({
    planId: 1,
    date,
    today: "2026-10-14",
    busy: false,
    onEaten,
    onReplan: vi.fn(async () => undefined),
    week: [],
  }) as unknown as MealActionsProps;

describe("MealCard one-tap eaten", () => {
  it("marks a meal that's due with one tap", () => {
    const onEaten = vi.fn(async () => undefined);
    renderWithClient(
      <MealCard meal={meal("dinner", 1, "Stew")} actions={props("2026-10-14", onEaten)} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Mark dinner eaten" }));

    expect(onEaten).toHaveBeenCalledWith({ date: "2026-10-14", slot: "dinner" }, false);
  });

  it("isn't offered for a future meal or one already eaten", () => {
    renderWithClient(<MealCard meal={meal("dinner", 1, "Stew")} actions={props("2026-10-15")} />);
    expect(screen.queryByRole("button", { name: "Mark dinner eaten" })).not.toBeInTheDocument();

    const eaten = { ...meal("lunch", 2, "Soup"), status: "eaten" as const };
    renderWithClient(<MealCard meal={eaten} actions={props("2026-10-14")} />);
    expect(screen.queryByRole("button", { name: "Mark lunch eaten" })).not.toBeInTheDocument();
  });
});
