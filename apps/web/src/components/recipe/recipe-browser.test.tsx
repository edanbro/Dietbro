import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RecipeListItem } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";
import { resetNavigation } from "@/test/navigation";

import { RecipeBrowser } from "./recipe-browser";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));

beforeEach(() => resetNavigation("/recipes"));
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

  it("shows what can be cooked from the pantry and what's still needed", async () => {
    const urls: URL[] = [];
    mockApi({
      "GET /recipes": (req: Request) => {
        const url = new URL(req.url);
        urls.push(url);
        return Response.json(
          url.searchParams.get("pantry") === "true"
            ? {
                items: [
                  item(1, "Traybake", { uses_pantry: ["Chicken, raw"], missing: [] }),
                  item(2, "Curry", {
                    uses_pantry: ["Chicken, raw"],
                    missing: ["Rice", "Garlic", "Spinach"],
                  }),
                ],
                total: 2,
              }
            : { items: [item(3, "Stew")], total: 1 },
        );
      },
    });
    renderWithClient(<RecipeBrowser />);
    await screen.findByText("1 recipe safe for you");

    const chip = screen.getByRole("button", { name: "From my pantry" });
    fireEvent.click(chip);

    expect(await screen.findByText("2 recipes using what's in your pantry")).toBeInTheDocument();
    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("link", { name: /Traybake/ })).toHaveTextContent("Nothing else to get");
    expect(screen.getByRole("link", { name: /Curry/ })).toHaveTextContent("Need rice, garlic +1");
    expect(urls[0]!.searchParams.has("pantry")).toBe(false);
  });

  it("opens on the pantry from ?pantry=1, and says when nothing can be cooked", async () => {
    resetNavigation("/recipes?pantry=1");
    const urls: URL[] = [];
    mockApi({
      "GET /recipes": (req: Request) => {
        urls.push(new URL(req.url));
        return Response.json({ items: [], total: 0 });
      },
    });
    renderWithClient(<RecipeBrowser />);

    expect(await screen.findByText("Nothing to cook from your pantry")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add to your pantry" })).toHaveAttribute(
      "href",
      "/pantry",
    );
    expect(urls[0]!.searchParams.get("pantry")).toBe("true");
    expect(screen.getByRole("button", { name: "From my pantry" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("starts a search from ?q= (food that's about to go off)", async () => {
    resetNavigation("/recipes?pantry=1&q=spinach%20milk");
    const urls: URL[] = [];
    mockApi({
      "GET /recipes": (req: Request) => {
        urls.push(new URL(req.url));
        return Response.json({ items: [], total: 0 });
      },
    });
    renderWithClient(<RecipeBrowser />);

    expect(await screen.findByRole("textbox", { name: "Search recipes" })).toHaveValue(
      "spinach milk",
    );
    await waitFor(() => expect(urls.length).toBeGreaterThan(0));
    expect(urls[0]!.searchParams.get("q")).toBe("spinach milk");
    expect(urls[0]!.searchParams.get("pantry")).toBe("true");
  });

  it("asks for the cheapest first", async () => {
    const urls: URL[] = [];
    mockApi({
      "GET /recipes": (req: Request) => {
        urls.push(new URL(req.url));
        return Response.json({ items: [], total: 0 });
      },
    });
    renderWithClient(<RecipeBrowser />);

    fireEvent.click(await screen.findByRole("button", { name: "Cheapest first" }));
    await waitFor(() => expect(urls.at(-1)!.searchParams.get("cheapest")).toBe("true"));
    expect(urls[0]!.searchParams.has("cheapest")).toBe(false);
  });

  it("shows what a serving costs on each recipe", async () => {
    mockApi({
      "GET /recipes": json({
        items: [item(1, "Coddle", { cost_per_serving: 182 }), item(2, "Boxty")],
        total: 2,
        currency: "GBP",
      }),
    });
    renderWithClient(<RecipeBrowser />);

    expect(await screen.findByRole("link", { name: /Coddle/ })).toHaveTextContent(
      "about £1.82 a serving",
    );
    expect(screen.getByRole("link", { name: /Boxty/ })).not.toHaveTextContent("a serving");
  });

  it("asks to finish setup first", async () => {
    mockApi({ "GET /recipes": json({ detail: ["Tell us first"] }, 409) });
    renderWithClient(<RecipeBrowser />);
    expect(await screen.findByRole("link", { name: "Set up" })).toHaveAttribute("href", "/setup");
  });
});
