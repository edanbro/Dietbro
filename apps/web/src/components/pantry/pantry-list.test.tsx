import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { daysUntil, ExpiryBadge, formatAmount, PantryList } from "./pantry-list";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));

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
    ["2026-11-01", "by Sun 1 Nov"],
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

describe("PantryList", () => {
  const item = (id: number, description: string, storage: string, extra = {}) => ({
    id,
    food: { id: id + 100, description, category: null, kcal: 100, kind: "food", source: "usda" },
    grams: 500,
    quantity: 500,
    unit: "g",
    approx: false,
    expires_on: null,
    source: "manual",
    created_at: "2026-10-01T09:00:00Z",
    storage,
    ...extra,
  });
  const ITEMS = [
    item(1, "Milk, whole", "fridge"),
    item(2, "Peas, frozen", "freezer"),
    item(3, "Rice, white", "cupboard"),
  ];

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("groups by where things are kept and searches", async () => {
    mockApi({ "GET /pantry": json(ITEMS) });
    renderWithClient(<PantryList />);

    expect(await screen.findByRole("region", { name: "Fridge" })).toHaveTextContent("Milk");
    expect(screen.getByRole("region", { name: "Freezer" })).toHaveTextContent("Frozen peas");
    fireEvent.change(screen.getByLabelText("Search your pantry"), { target: { value: "ric" } });
    expect(screen.queryByText("Milk · whole")).not.toBeInTheDocument();
    expect(screen.getByText("White rice")).toBeInTheDocument();
  });

  it("edits an item", async () => {
    const calls = mockApi({
      "GET /pantry": json(ITEMS),
      "GET /foods/101": json({ units: [{ unit: "g" }, { unit: "ml" }] }),
      "PATCH /pantry/1": json(ITEMS[0]),
    });
    renderWithClient(<PantryList />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit Milk, whole" }));
    fireEvent.change(screen.getByLabelText("Quantity left"), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        quantity: 250,
        unit: "g",
        expires_on: null,
      }),
    );
  });

  it("moves an item to the freezer, and a near use-by out to three months", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(TODAY);
    const milk = item(1, "Milk, whole", "fridge", { expires_on: "2026-10-10" });
    const calls = mockApi({
      "GET /pantry": json([milk]),
      "GET /foods/101": json({ units: [{ unit: "g" }] }),
      "PATCH /pantry/1": json(milk),
    });
    renderWithClient(<PantryList />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit Milk, whole" }));
    fireEvent.change(screen.getByLabelText("Kept in"), { target: { value: "freezer" } });
    expect(screen.getByLabelText("Use by")).toHaveValue("2027-01-06");
    expect(screen.getByRole("status")).toHaveTextContent("Frozen, it keeps for months");
    // Changing your mind puts the date back.
    fireEvent.change(screen.getByLabelText("Kept in"), { target: { value: "fridge" } });
    expect(screen.getByLabelText("Use by")).toHaveValue("2026-10-10");
    fireEvent.change(screen.getByLabelText("Kept in"), { target: { value: "freezer" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        quantity: 500,
        unit: "g",
        expires_on: "2027-01-06",
        storage: "freezer",
      }),
    );
  });

  it("waits before deleting so it can be undone", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = mockApi({ "GET /pantry": json(ITEMS), "DELETE /pantry/3": json(null) });
    renderWithClient(<PantryList />);

    fireEvent.click(await screen.findByRole("button", { name: "Remove Rice, white" }));
    expect(screen.queryByText("Rice, white")).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    await vi.advanceTimersByTimeAsync(5000);
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});
