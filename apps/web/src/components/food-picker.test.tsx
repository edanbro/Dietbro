import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithClient } from "@/test/api";

import { FoodPicker } from "./food-picker";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));

afterEach(() => vi.unstubAllGlobals());

function food(id: number, extra: Record<string, unknown> = {}) {
  return {
    id,
    description: `Butter ${id}`,
    category: "Dairy and Egg Products",
    kcal: 717,
    kind: "food",
    source: "usda",
    ...extra,
  };
}

describe("FoodPicker", () => {
  it("shows brands and a Product badge, and loads more results", async () => {
    const calls = mockApi({
      "GET /foods/search": (req) => {
        const offset = Number(new URL(req.url).searchParams.get("offset"));
        const page =
          offset === 0
            ? [
                ...Array.from({ length: 19 }, (_, i) => food(i + 1)),
                food(100, { brand: "Kerrygold", description: "Pure Irish Butter", kind: "product" }),
              ]
            : [food(200)];
        return Response.json(page);
      },
    });
    const onPick = vi.fn();
    renderWithClient(<FoodPicker onPick={onPick} />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "butter" } });

    const product = await screen.findByRole("button", { name: /Pure Irish Butter/ });
    expect(product).toHaveTextContent(/Kerrygold\s+Pure Irish Butter/);
    expect(product).toHaveTextContent("Product");
    fireEvent.click(screen.getByRole("button", { name: "More results" }));
    expect(await screen.findByRole("button", { name: /Butter 200/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More results" })).not.toBeInTheDocument();
    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/foods/search")).toHaveLength(2),
    );

    fireEvent.click(product);
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 100, brand: "Kerrygold" }));
  });

  it("asks for foods only when scoped to generic", async () => {
    let scope: string | null = null;
    mockApi({
      "GET /foods/search": (req) => {
        scope = new URL(req.url).searchParams.get("scope");
        return Response.json([food(1)]);
      },
    });
    renderWithClient(<FoodPicker onPick={vi.fn()} scope="generic" />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "peanut" } });

    await screen.findByRole("button", { name: /Butter 1/ });
    expect(scope).toBe("generic");
  });
});
