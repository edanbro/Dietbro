import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";

import { deferred, json, mockApi, renderWithClient, type Routes } from "@/test/api";
import { makePlan, makeShoppingList } from "@/test/fixtures";

import { aisle, groupByAisle, ShoppingPage } from "./shopping-page";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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
    const onions = within(veg).getByRole("checkbox", { name: "Onions, raw" });
    expect(onions).toHaveAccessibleDescription("450 g · ≈ 3 medium");
    expect(veg).toHaveTextContent("£0.60");

    const dairy = screen.getByRole("region", { name: "Dairy & eggs" });
    expect(within(dairy).getByRole("checkbox", { name: "Milk, whole" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(dairy).toHaveTextContent("1.3 kg");

    const staples = screen.getByRole("region", { name: "Check you have" });
    expect(within(staples).getByRole("checkbox", { name: "Salt, table" })).toBeInTheDocument();
    expect(staples).not.toHaveTextContent("£");

    expect(screen.getByText("≈ £12.34")).toBeInTheDocument();
    expect(screen.getByText("Budget £50.00")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 ticked")).toBeInTheDocument();
    expect(screen.getByText("For Fri 9 Oct – Thu 15 Oct")).toBeInTheDocument();
  });

  it("warns when the list costs more than the budget", async () => {
    setup({ "GET /plans/7/shopping": json(makeShoppingList({ total_minor: 5600 })) });

    expect(await screen.findByText(/£6.00 over your £50.00 budget/)).toBeInTheDocument();
  });

  it("ticks optimistically and saves", async () => {
    const gate = deferred<void>();
    const server = shoppingServer({ gate: { 11: gate.promise } });
    const calls = setup(server.routes);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Onions, raw" }));

    // Checked before the server answers.
    await waitFor(() => expect(box("Onions, raw")).toHaveAttribute("aria-checked", "true"));
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
    expect(box("Onions, raw")).toHaveAttribute("aria-checked", "true");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("rolls back the line and says so when saving fails", async () => {
    // The resync after the failure never answers, so the rollback must come from the cache.
    const gate = deferred<void>();
    const server = shoppingServer({ fail: [13], gate: { 13: gate.promise }, refetch: "hang" });
    setup(server.routes);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Milk, whole" }));
    await waitFor(() => expect(box("Milk, whole")).toHaveAttribute("aria-checked", "false"));

    gate.resolve();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Milk, whole")),
    );
    expect(box("Milk, whole")).toHaveAttribute("aria-checked", "true");
  });

  it("sends ticks one at a time, in order", async () => {
    const gate = deferred<void>();
    const server = shoppingServer({ gate: { 11: gate.promise } });
    const calls = setup(server.routes);
    const patches = () => calls.filter((c) => c.method === "PATCH").map((c) => c.path);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Onions, raw" }));
    fireEvent.click(box("Spinach, raw"));

    // Both boxes flip at once…
    await waitFor(() => expect(box("Spinach, raw")).toHaveAttribute("aria-checked", "true"));
    expect(box("Onions, raw")).toHaveAttribute("aria-checked", "true");
    // …but the second request waits for the first.
    await new Promise((r) => setTimeout(r, 30));
    expect(patches()).toEqual(["/plans/7/shopping/11"]);

    gate.resolve();

    await waitFor(() =>
      expect(patches()).toEqual(["/plans/7/shopping/11", "/plans/7/shopping/12"]),
    );
    await waitFor(() => expect(server.list.items[1].checked).toBe(true));
    expect(box("Onions, raw")).toHaveAttribute("aria-checked", "true");
    expect(box("Spinach, raw")).toHaveAttribute("aria-checked", "true");
  });

  it("keeps a later tick when an earlier one fails", async () => {
    const gate = deferred<void>();
    const server = shoppingServer({ gate: { 11: gate.promise }, fail: [11] });
    setup(server.routes);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Onions, raw" }));
    fireEvent.click(box("Spinach, raw"));
    await waitFor(() => expect(box("Spinach, raw")).toHaveAttribute("aria-checked", "true"));

    gate.resolve();

    await waitFor(() => expect(box("Onions, raw")).toHaveAttribute("aria-checked", "false"));
    await waitFor(() => expect(server.list.items[1].checked).toBe(true));
    expect(box("Spinach, raw")).toHaveAttribute("aria-checked", "true");
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("points to the plan when there isn't one", async () => {
    setup({ "GET /plans/current": json(null) });

    expect(await screen.findByText(/No plan yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plan my week" })).toHaveAttribute("href", "/plan");
  });
});
