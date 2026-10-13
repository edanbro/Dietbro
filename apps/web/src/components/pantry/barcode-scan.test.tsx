import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { BarcodeScan } from "./barcode-scan";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));

afterEach(() => vi.unstubAllGlobals());

const KERRYGOLD = {
  id: 1_000_000_002,
  description: "Pure Irish Butter",
  brand: "Kerrygold",
  category: "Dairy and Egg Products",
  kcal: 740,
  kind: "product",
  source: "off",
  barcode: "5000159407236",
  units: [{ unit: "packet", grams_each: 227 }],
  allergens: ["milk"],
  may_contain: [],
  counts_as: null,
  attribution: "Open Food Facts contributors (Open Database License)",
};

function open() {
  fireEvent.click(screen.getByRole("button", { name: "Scan a barcode" }));
}

describe("BarcodeScan", () => {
  it("falls back to typing when there is no camera", async () => {
    mockApi({});
    renderWithClient(<BarcodeScan onFound={vi.fn()} />);

    open();

    expect(await screen.findByText(/Type the barcode instead/)).toBeInTheDocument();
  });

  it("looks up typed digits and hands over the product", async () => {
    const calls = mockApi({ "GET /foods/barcode/5000159407236": json(KERRYGOLD) });
    const onFound = vi.fn();
    renderWithClient(<BarcodeScan onFound={onFound} />);
    open();

    const lookUp = screen.getByRole("button", { name: "Look up" });
    expect(lookUp).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Or type the digits"), {
      target: { value: "5000159 407236" },
    });
    fireEvent.click(lookUp);

    await vi.waitFor(() => expect(onFound).toHaveBeenCalledWith(KERRYGOLD));
    expect(calls.map((c) => c.path)).toEqual(["/foods/barcode/5000159407236"]);
    expect(screen.getByRole("button", { name: "Scan a barcode" })).toBeInTheDocument();
  });

  it("says when a barcode isn't known", async () => {
    mockApi({
      "GET /foods/barcode/96385074": json(
        { detail: ["We don't know that barcode yet. Search for the food by name instead."] },
        404,
      ),
    });
    renderWithClient(<BarcodeScan onFound={vi.fn()} />);
    open();

    fireEvent.change(screen.getByLabelText("Or type the digits"), { target: { value: "96385074" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Search for the food by name");
  });
});
