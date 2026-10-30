import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { gramsEach, QuickAdd, slotNow } from "./quick-add";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => vi.unstubAllGlobals());

const BANANA = {
  id: 9040,
  description: "Bananas, raw",
  category: "Fruits and Fruit Juices",
  kcal: 89,
  kind: "food",
  source: "usda",
};

describe("slotNow", () => {
  it("picks the meal by the clock", () => {
    expect(slotNow(new Date(2026, 9, 14, 8))).toBe("breakfast");
    expect(slotNow(new Date(2026, 9, 14, 13))).toBe("lunch");
    expect(slotNow(new Date(2026, 9, 14, 19))).toBe("dinner");
    expect(slotNow(new Date(2026, 9, 14, 22))).toBe("evening_snack");
  });
});

describe("gramsEach", () => {
  it("weighs grams, kilograms and the food's own units", () => {
    const units = [{ unit: "medium", grams_each: 118 }];
    expect(gramsEach("g", units)).toBe(1);
    expect(gramsEach("kg", units)).toBe(1000);
    expect(gramsEach("medium", units)).toBe(118);
    expect(gramsEach("cup", units)).toBeNull();
  });
});

describe("QuickAdd", () => {
  it("turns typed words into foods to check, and logs only on the second step", async () => {
    const calls = mockApi({
      "GET /foods/9040": json({ ...BANANA, units: [{ unit: "g", grams_each: 1 }] }),
      "POST /diary/parse": json({
        items: [{ name: "banana", food: BANANA, grams: 118, estimated: true }],
        unmatched: ["moon rock"],
      }),
      "POST /diary/log": json({ type: "outcome", results: [{ message: "Logged bananas" }] }),
    });
    renderWithClient(<QuickAdd />);

    fireEvent.click(screen.getByRole("button", { name: "Add food" }));
    const typed = screen.getByLabelText("Type what you had");
    fireEvent.change(typed, { target: { value: "a banana and a moon rock" } });
    fireEvent.keyDown(typed, { key: "Enter" });

    const amount = await screen.findByLabelText("Amount of Bananas");
    expect(amount).toHaveValue(118);
    expect(typed).toHaveValue("");
    expect(screen.getByText(/typical portion/)).toBeInTheDocument();
    expect(screen.getByText(/find moon rock/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/diary/parse")?.body).toMatchObject({
      text: "a banana and a moon rock",
    });
    expect(calls.some((c) => c.path === "/diary/log")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Log it" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/diary/log")).toBe(true));
  });

  it("logs a picked food in its own unit for the chosen meal", async () => {
    const calls = mockApi({
      "GET /foods/search": json([BANANA]),
      "GET /foods/9040": json({ ...BANANA, units: [{ unit: "g", grams_each: 1 }, { unit: "medium", grams_each: 118 }] }),
      "POST /diary/log": json({ type: "outcome", results: [{ message: "Logged bananas" }] }),
    });
    renderWithClient(<QuickAdd />);

    fireEvent.click(screen.getByRole("button", { name: "Add food" }));
    const submit = screen.getByRole("button", { name: "Log it" });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Meal"), { target: { value: "snack" } });
    fireEvent.change(screen.getByRole("textbox", { name: /Search foods/ }), {
      target: { value: "banana" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Bananas/ }));
    await screen.findByRole("option", { name: "medium" });
    fireEvent.change(screen.getByLabelText("Unit for Bananas"), { target: { value: "medium" } });
    fireEvent.change(screen.getByLabelText("Amount of Bananas"), { target: { value: "2" } });
    fireEvent.click(submit);

    await waitFor(() => expect(calls.some((c) => c.path === "/diary/log")).toBe(true));
    const sent = calls.find((c) => c.path === "/diary/log")!.body as Record<string, unknown>;
    expect(sent).toMatchObject({ slot: "snack", items: [{ food_id: 9040, grams: 236 }] });
    expect(await screen.findByRole("button", { name: "Add food" })).toBeInTheDocument();
  });

  it("offers recent food to log again at its amounts", async () => {
    const yogurt = { ...BANANA, id: 1500, description: "Yogurt, Greek, plain, whole milk" };
    const calls = mockApi({
      "GET /diary/recent": json([
        {
          description: "bananas, raw and yogurt",
          kcal: 230,
          last_eaten_on: "2026-10-13",
          items: [
            { food: BANANA, grams: 118 },
            { food: yogurt, grams: 150 },
          ],
        },
      ]),
      "GET /foods/9040": json({ ...BANANA, units: [{ unit: "g", grams_each: 1 }] }),
      "GET /foods/1500": json({ ...yogurt, units: [{ unit: "g", grams_each: 1 }] }),
      "POST /diary/log": json({ type: "outcome", results: [{ message: "Logged" }] }),
    });
    renderWithClient(<QuickAdd />);

    fireEvent.click(screen.getByRole("button", { name: "Add food" }));
    const again = await screen.findByRole("button", { name: "Bananas + Yogurt · 230 kcal" });
    fireEvent.click(again);
    expect(screen.queryByRole("heading", { name: "Recent" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Amount of Bananas")).toHaveValue(118);
    fireEvent.click(screen.getByRole("button", { name: "Log it" }));

    await waitFor(() => expect(calls.some((c) => c.path === "/diary/log")).toBe(true));
    const sent = calls.find((c) => c.path === "/diary/log")!.body as Record<string, unknown>;
    expect(sent).toMatchObject({
      items: [
        { food_id: 9040, grams: 118 },
        { food_id: 1500, grams: 150 },
      ],
    });
  });
});
