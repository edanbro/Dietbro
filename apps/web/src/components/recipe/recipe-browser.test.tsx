import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RecipeListItem } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";

import { RecipeBrowser } from "./recipe-browser";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

afterEach(() => vi.unstubAllGlobals());

const item = (id: number, name: string, extra: Partial<RecipeListItem> = {}): RecipeListItem => ({
  id,
  name,
  category: "Chicken",
  cuisine: "Irish",
  image_url: null,
  slots: ["dinner"],
  kcal_per_serving: 620,
  protein_g_per_serving: 45,
  uses_pantry: [],
  favourite: false,
  ...extra,
});

describe("RecipeBrowser", () => {
  it("lists safe recipes and pages through them", async () => {
    const calls = mockApi({
      "GET /recipes": (req: Request) => {
        const offset = Number(new URL(req.url).searchParams.get("offset"));
        return Response.json(
          offset === 0
            ? {
                items: [
                  item(1, "Irish stew", { favourite: true }),
                  item(2, "Coddle", { uses_pantry: ["Onions"] }),
                ],
                total: 3,
              }
            : { items: [item(3, "Boxty")], total: 3 },
        );
      },
    });
    renderWithClient(<RecipeBrowser />);

    const list = await screen.findByText("3 recipes safe for you");
    expect(list).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Irish stew/ })).toHaveAttribute("href", "/recipes/1");
    expect(screen.getByLabelText("Favourite")).toBeInTheDocument();
    expect(screen.getByText("Uses your onions")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "More recipes" }));
    expect(await screen.findByRole("link", { name: /Boxty/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More recipes" })).not.toBeInTheDocument();
    expect(new URL(`http://x${calls.at(-1)!.path}`).pathname).toBe("/recipes");
  });

  it("filters by meal and favourites", async () => {
    const urls: URL[] = [];
    mockApi({
      "GET /recipes": (req: Request) => {
        urls.push(new URL(req.url));
        return Response.json({ items: [], total: 0 });
      },
    });
    renderWithClient(<RecipeBrowser />);
    await screen.findByText(/No safe recipe matches/);

    const filters = screen.getByRole("group", { name: "Filters" });
    fireEvent.click(within(filters).getByRole("button", { name: "Breakfast" }));
    fireEvent.click(within(filters).getByRole("button", { name: "Favourites" }));

    await waitFor(() =>
      expect(
        urls.some(
          (u) =>
            u.searchParams.get("slot") === "breakfast" &&
            u.searchParams.get("favourites") === "true",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText(/No favourites yet/)).toBeInTheDocument();
  });

  it("shows how long recipes take and filters quick ones", async () => {
    const urls: URL[] = [];
    mockApi({
      "GET /recipes": (req: Request) => {
        urls.push(new URL(req.url));
        return Response.json({ items: [item(1, "Omelette", { minutes: 15 })], total: 1 });
      },
    });
    renderWithClient(<RecipeBrowser />);
    expect(await screen.findByRole("link", { name: /Omelette/ })).toHaveTextContent("about 15 min");

    fireEvent.click(screen.getByRole("button", { name: "Under 30 min" }));

    await waitFor(() =>
      expect(urls.some((u) => u.searchParams.get("max_minutes") === "30")).toBe(true),
    );
    expect(urls[0]!.searchParams.has("max_minutes")).toBe(false);
  });

  it("asks to finish setup first", async () => {
    mockApi({ "GET /recipes": json({ detail: ["Tell us first"] }, 409) });
    renderWithClient(<RecipeBrowser />);
    expect(await screen.findByRole("link", { name: "Set up" })).toHaveAttribute("href", "/setup");
  });
});
