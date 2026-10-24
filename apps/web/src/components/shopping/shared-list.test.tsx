import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { deferred, json, mockApi } from "@/test/api";

import { POLL_MS, type SharedList, SharedShoppingList } from "./shared-list";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const LIST: SharedList = {
  start: "2026-10-09",
  household: 3,
  units: "metric",
  items: [
    {
      food_id: 11,
      name: "Onions, raw",
      category: "Vegetables and Vegetable Products",
      grams: 450,
      approx_units: "≈ 3 medium",
      checked: false,
      staple: false,
    },
    {
      food_id: 12,
      name: "Chicken, breast, raw",
      category: "Poultry Products",
      grams: 600,
      approx_units: null,
      checked: true,
      staple: false,
    },
    {
      food_id: 13,
      name: "Salt, table",
      category: "Spices and Herbs",
      grams: 0,
      approx_units: null,
      checked: false,
      staple: true,
    },
  ],
  extras: [{ id: 5, name: "Bin bags", checked: false }],
};

const ticked = (list: SharedList, foodId: number): SharedList => ({
  ...list,
  items: list.items.map((i) => (i.food_id === foodId ? { ...i, checked: true } : i)),
});

const box = (name: string) => screen.getByRole("checkbox", { name });

describe("SharedShoppingList", () => {
  it("shows the week's list by aisle, for everyone, without prices", () => {
    mockApi({});
    render(<SharedShoppingList token="tok" initial={LIST} />);

    expect(screen.getByRole("heading", { name: "Shopping list" })).toBeInTheDocument();
    expect(screen.getByText("For Fri 9 Oct – Thu 15 Oct, 3 people")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 ticked")).toBeInTheDocument();
    expect(screen.getByText(/^450 g · ≈ 3 medium/)).toBeInTheDocument();
    expect(box("Chicken")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("heading", { name: "Check you have" })).toBeInTheDocument();
    expect(box("Bin bags")).toBeInTheDocument();
    expect(screen.queryByText(/£/)).not.toBeInTheDocument();
  });

  it("ticks at once, saves, then shows the list as saved", async () => {
    const saved = deferred<void>();
    const calls = mockApi({
      "PATCH /public/share/tok/items/11": async () => {
        await saved.promise;
        return Response.json(ticked(LIST, 11));
      },
    });
    render(<SharedShoppingList token="tok" initial={LIST} />);

    fireEvent.click(box("Onions"));

    await waitFor(() => expect(box("Onions")).toHaveAttribute("aria-checked", "true"));
    expect(calls).toEqual([
      { method: "PATCH", path: "/public/share/tok/items/11", body: { checked: true } },
    ]);
    saved.resolve();
    expect(await screen.findByText("2 of 3 ticked")).toBeInTheDocument();
  });

  it("ticks the owner's own items too", async () => {
    const calls = mockApi({
      "PATCH /public/share/tok/extras/5": json({
        ...LIST,
        extras: [{ id: 5, name: "Bin bags", checked: true }],
      }),
    });
    render(<SharedShoppingList token="tok" initial={LIST} />);

    fireEvent.click(box("Bin bags"));

    await waitFor(() => expect(box("Bin bags")).toHaveAttribute("aria-checked", "true"));
    expect(calls[0]).toMatchObject({ path: "/public/share/tok/extras/5", body: { checked: true } });
  });

  it("puts a tick back and says so when it can't be saved", async () => {
    mockApi({ "PATCH /public/share/tok/items/11": json({ detail: "boom" }, 500) });
    render(<SharedShoppingList token="tok" initial={LIST} />);

    fireEvent.click(box("Onions"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save that tick");
    expect(box("Onions")).toHaveAttribute("aria-checked", "false");
  });

  it("says when the list isn't shared any more", async () => {
    mockApi({}); // every route answers 404
    render(<SharedShoppingList token="tok" initial={LIST} />);

    fireEvent.click(box("Onions"));

    expect(await screen.findByRole("alert")).toHaveTextContent("This list isn't shared any more.");
  });

  it("reads the list again now and then, so the others' ticks show up", async () => {
    vi.useFakeTimers();
    const calls = mockApi({
      "GET /public/share/tok": json({ kind: "list", shopping: ticked(LIST, 11) }),
    });
    render(<SharedShoppingList token="tok" initial={LIST} />);
    expect(box("Onions")).toHaveAttribute("aria-checked", "false");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });

    expect(calls.map((c) => c.path)).toEqual(["/public/share/tok"]);
    expect(box("Onions")).toHaveAttribute("aria-checked", "true");
  });
});
