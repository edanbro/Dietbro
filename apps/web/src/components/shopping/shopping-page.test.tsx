import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";

import { deferred, json, mockApi, renderWithClient, type Routes } from "@/test/api";
import { aisle } from "@/lib/aisles";
import { item, makePlan, makeShoppingList } from "@/test/fixtures";

import { groupByAisle, listText, ShoppingPage } from "./shopping-page";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function setup(routes: Routes = {}) {
  const calls = mockApi({
    "GET /plans/current": json(makePlan()),
    "GET /plans/7/shopping": json(makeShoppingList()),
    ...routes,
  });
  renderWithClient(<ShoppingPage />);
  return calls;
}

const box = (name: string) => screen.getByRole("checkbox", { name });

/** A stateful fake of the shopping endpoints: PATCH changes what the next GET returns. */
function shoppingServer({
  fail = [],
  gate = {},
  refetch = "serve",
}: {
  fail?: number[];
  gate?: Record<number, Promise<void>>;
  refetch?: "serve" | "hang";
} = {}) {
  const list = makeShoppingList();
  let gets = 0;
  const routes: Routes = {
    "GET /plans/7/shopping": () => {
      gets += 1;
      if (gets > 1 && refetch === "hang") return new Promise<Response>(() => {});
      return Response.json(structuredClone(list));
    },
  };
  for (const line of list.items) {
    routes[`PATCH /plans/7/shopping/${line.food_id}`] = async (req) => {
      const { checked } = (await req.json()) as { checked: boolean };
      await gate[line.food_id];
      if (fail.includes(line.food_id)) return Response.json({ detail: "boom" }, { status: 500 });
      line.checked = checked;
      return Response.json(line);
    };
  }
  return { list, routes };
}

describe("grouping", () => {
  it("maps USDA groups to aisles, keeping the API's order", () => {
    expect(aisle(null)).toBe("Other");
    expect(aisle("Beef Products")).toBe("Meat");
    expect(aisle("Something New")).toBe("Something New");
    const groups = groupByAisle(makeShoppingList().items.filter((i) => !i.staple));
    expect(groups.map(([name, items]) => [name, items.map((i) => i.food_id)])).toEqual([
      ["Vegetables", [11, 12]],
      ["Dairy & eggs", [13]],
    ]);
  });
});

describe("ShoppingPage", () => {
  it("lists what to buy by aisle, staples to check, and the total against the budget", async () => {
    setup();

    const veg = await screen.findByRole("region", { name: "Vegetables" });
    expect(
      within(veg)
        .getAllByRole("checkbox")
        .map((c) => c.getAttribute("aria-checked")),
    ).toEqual(["false", "false"]);
    const onions = within(veg).getByRole("checkbox", { name: "Onions" });
    expect(onions).toHaveAccessibleDescription("450 g · ≈ 3 medium");
    expect(veg).toHaveTextContent("£0.60");

    const dairy = screen.getByRole("region", { name: "Dairy & eggs" });
    expect(within(dairy).getByRole("checkbox", { name: "Milk" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(dairy).toHaveTextContent("1.3 kg");

    const staples = screen.getByRole("region", { name: "Check you have" });
    expect(within(staples).getByRole("checkbox", { name: "Salt" })).toBeInTheDocument();
    expect(staples).not.toHaveTextContent("£");

    expect(screen.getByText("≈ £12.34")).toBeInTheDocument();
    expect(screen.getByText("Budget £50.00")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 ticked")).toBeInTheDocument();
    expect(screen.getByText("For Fri 9 Oct – Thu 15 Oct")).toBeInTheDocument();
  });

  it("says who the list is for when the plan is for a household", async () => {
    setup({ "GET /plans/7/shopping": json(makeShoppingList({ household: 3 })) });

    expect(await screen.findByText("Estimated total, for 3 people")).toBeInTheDocument();
  });

  it("warns when the list costs more than the budget", async () => {
    setup({ "GET /plans/7/shopping": json(makeShoppingList({ total_minor: 5600 })) });

    expect(await screen.findByText(/£6.00 over your £50.00 budget/)).toBeInTheDocument();
  });

  it("ticks optimistically and saves", async () => {
    const gate = deferred<void>();
    const server = shoppingServer({ gate: { 11: gate.promise } });
    const calls = setup(server.routes);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Onions" }));

    // Checked before the server answers.
    await waitFor(() => expect(box("Onions")).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByText("2 of 3 ticked")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")).toMatchObject({
      path: "/plans/7/shopping/11",
      body: { checked: true },
    });

    gate.resolve();

    await waitFor(() => expect(server.list.items[0].checked).toBe(true));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "GET" && c.path.endsWith("/shopping"))).toHaveLength(
        2,
      ),
    );
    expect(box("Onions")).toHaveAttribute("aria-checked", "true");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("rolls back the line and says so when saving fails", async () => {
    // The resync after the failure never answers, so the rollback must come from the cache.
    const gate = deferred<void>();
    const server = shoppingServer({ fail: [13], gate: { 13: gate.promise }, refetch: "hang" });
    setup(server.routes);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Milk" }));
    await waitFor(() => expect(box("Milk")).toHaveAttribute("aria-checked", "false"));

    gate.resolve();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Milk, whole")),
    );
    expect(box("Milk")).toHaveAttribute("aria-checked", "true");
  });

  it("sends ticks one at a time, in order", async () => {
    const gate = deferred<void>();
    const server = shoppingServer({ gate: { 11: gate.promise } });
    const calls = setup(server.routes);
    const patches = () => calls.filter((c) => c.method === "PATCH").map((c) => c.path);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Onions" }));
    fireEvent.click(box("Spinach"));

    // Both boxes flip at once…
    await waitFor(() => expect(box("Spinach")).toHaveAttribute("aria-checked", "true"));
    expect(box("Onions")).toHaveAttribute("aria-checked", "true");
    // …but the second request waits for the first.
    await new Promise((r) => setTimeout(r, 30));
    expect(patches()).toEqual(["/plans/7/shopping/11"]);

    gate.resolve();

    await waitFor(() =>
      expect(patches()).toEqual(["/plans/7/shopping/11", "/plans/7/shopping/12"]),
    );
    await waitFor(() => expect(server.list.items[1].checked).toBe(true));
    expect(box("Onions")).toHaveAttribute("aria-checked", "true");
    expect(box("Spinach")).toHaveAttribute("aria-checked", "true");
  });

  it("keeps a later tick when an earlier one fails", async () => {
    const gate = deferred<void>();
    const server = shoppingServer({ gate: { 11: gate.promise }, fail: [11] });
    setup(server.routes);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Onions" }));
    fireEvent.click(box("Spinach"));
    await waitFor(() => expect(box("Spinach")).toHaveAttribute("aria-checked", "true"));

    gate.resolve();

    await waitFor(() => expect(box("Onions")).toHaveAttribute("aria-checked", "false"));
    await waitFor(() => expect(server.list.items[1].checked).toBe(true));
    expect(box("Spinach")).toHaveAttribute("aria-checked", "true");
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("points to the plan when there isn't one", async () => {
    setup({ "GET /plans/current": json(null) });

    expect(await screen.findByText(/Nothing to buy yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plan my week" })).toHaveAttribute("href", "/plan");
  });
});


describe("Shopping to pantry and your own items", () => {
  const ticked = makeShoppingList({
    items: [
      item({ food_id: 11, name: "Onions, raw", checked: true }),
      item({ food_id: 12, name: "Spinach, raw", checked: true, stocked: true }),
      item({ food_id: 13, name: "Rice, white" }),
    ],
  });

  it("moves ticked lines not moved yet into the pantry", async () => {
    const calls = setup({
      "GET /plans/7/shopping": json(ticked),
      "GET /shopping/extras": json([]),
      "POST /plans/7/shopping/stock": json([{ id: 1 }], 201),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Move 1 ticked to pantry" }));

    await waitFor(() => expect(calls.some((c) => c.path === "/plans/7/shopping/stock")).toBe(true));
    expect(calls.find((c) => c.path === "/plans/7/shopping/stock")?.body).toEqual({
      food_ids: null,
    });
    expect(screen.getByText(/· in your pantry/)).toBeInTheDocument();
  });

  it("hides ticked lines on request", async () => {
    setup({ "GET /plans/7/shopping": json(ticked), "GET /shopping/extras": json([]) });

    fireEvent.click(await screen.findByRole("switch", { name: "Hide ticked" }));

    expect(screen.queryByText("Onions, raw")).not.toBeInTheDocument();
    expect(screen.getByText("White rice")).toBeInTheDocument();
  });

  it("adds your own items", async () => {
    const calls = setup({
      "GET /shopping/extras": json([{ id: 1, name: "foil", checked: false }]),
      "POST /shopping/extras": json({ id: 2, name: "bin bags", checked: false }, 201),
    });

    expect(await screen.findByText("foil")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Add your own item"), { target: { value: "bin bags" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path === "/shopping/extras")?.body).toEqual(
        { name: "bin bags" },
      ),
    );
  });

  it("writes the list as text by aisle, without ticked or staple lines", () => {
    const list = makeShoppingList({
      items: [
        item({ food_id: 1, name: "Onions, raw", category: "Vegetables and Vegetable Products", approx_units: "≈ 3 medium" }),
        item({ food_id: 2, name: "Rice, white", category: "Cereal Grains and Pasta", grams: 1000 }),
        item({ food_id: 3, name: "Spinach, raw", checked: true }),
        item({ food_id: 4, name: "Salt", staple: true }),
      ],
    });

    expect(listText(list, [{ id: 1, name: "foil", checked: false }])).toBe(
      [
        "Vegetables:",
        "- Onions (≈ 3 medium)",
        "Grains & pasta:",
        "- White rice (1 kg)",
        "Also:",
        "- foil",
      ].join("\n"),
    );
    expect(listText(list, [], "us")).toContain("- White rice (2.2 lb)");
  });
});

describe("sharing the list", () => {
  it("offers a live link to shop together, and the list as text", async () => {
    const calls = setup({ "POST /share": json({ token: "list1", path: "/s/list1" }) });
    vi.stubGlobal("navigator", {
      ...navigator,
      share: undefined,
      clipboard: { writeText: vi.fn(async () => undefined) },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Shop together" }));

    await waitFor(() =>
      expect(calls.find((c) => c.path === "/share")?.body).toEqual({
        kind: "list",
        start: "2026-10-09",
      }),
    );
    expect(screen.getByRole("button", { name: "Send as text" })).toBeInTheDocument();
  });
});

describe("printing the list", () => {
  it("prints from the list's own button", async () => {
    const print = vi.fn();
    vi.stubGlobal("print", print);
    setup();

    vi.mocked(print).mockClear();
    (await screen.findByRole("button", { name: "Print" })).click();

    expect(print).toHaveBeenCalledOnce();
  });
});
