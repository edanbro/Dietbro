import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/components/providers";
import {
  keys,
  type ShoppingItem,
  useOfflineSync,
  useShoppingList,
  useTickShoppingItem,
} from "@/lib/api/hooks";

import {
  clearOfflineData,
  dropTicks,
  loadSnapshot,
  pendingTicks,
  queueTick,
  saveSnapshot,
} from "./offline";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ userId: "user_1", getToken: async () => "t" }),
}));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

const MILK: ShoppingItem = {
  food_id: 11,
  name: "Milk",
  category: "Dairy and Egg Products",
  grams: 1000,
  cost_minor: 100,
  till_minor: 100,
  checked: false,
  stocked: false,
  staple: false,
};
const LIST = { plan_id: 7, currency: "GBP", total_minor: 100, items: [MILK] };

let online = true;
beforeEach(() => {
  localStorage.clear();
  online = true;
  vi.spyOn(navigator, "onLine", "get").mockImplementation(() => online);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("offline storage", () => {
  it("keeps copies per user", () => {
    saveSnapshot("a", "plan", { id: 1 });
    expect(loadSnapshot("a", "plan")).toEqual({ id: 1 });
    expect(loadSnapshot("b", "plan")).toBeUndefined();
    expect(loadSnapshot(null, "plan")).toBeUndefined();
  });

  it("queues ticks, the latest per line, and drops the sent ones", () => {
    queueTick("a", { planId: 7, foodId: 11, checked: true });
    queueTick("a", { planId: 7, foodId: 12, checked: true });
    queueTick("a", { planId: 7, foodId: 11, checked: false });
    expect(pendingTicks("a")).toEqual([
      { planId: 7, foodId: 12, checked: true },
      { planId: 7, foodId: 11, checked: false },
    ]);
    dropTicks("a", [{ planId: 7, foodId: 12, checked: true }]);
    expect(pendingTicks("a")).toEqual([{ planId: 7, foodId: 11, checked: false }]);
  });

  it("forgets everything on sign-out", () => {
    saveSnapshot("a", "plan", { id: 1 });
    queueTick("a", { planId: 7, foodId: 11, checked: true });
    localStorage.setItem("theme", "dark");
    clearOfflineData();
    expect(loadSnapshot("a", "plan")).toBeUndefined();
    expect(pendingTicks("a")).toEqual([]);
    expect(localStorage.getItem("theme")).toBe("dark"); // not ours to clear
  });
});

describe("shopping offline", () => {
  it("shows the last copy, keeps offline ticks and sends them when back online", async () => {
    const patches: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (req: Request) => {
        if (!online) throw new TypeError("Failed to fetch");
        if (req.method === "PATCH") {
          patches.push(`${new URL(req.url).pathname} ${await req.text()}`);
          return Response.json({ ...MILK, checked: true });
        }
        return Response.json(LIST);
      }),
    );
    const client = makeQueryClient();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    // Online once: the list is kept.
    const first = renderHook(() => useShoppingList(7), { wrapper });
    await waitFor(() => expect(first.result.current.data?.items).toHaveLength(1));
    first.unmount();
    client.clear();

    // Offline: the copy shows at once, and a tick is kept.
    online = false;
    const { result } = renderHook(
      () => ({ list: useShoppingList(7), tick: useTickShoppingItem(7) }),
      { wrapper },
    );
    expect(result.current.list.data?.items[0]?.name).toBe("Milk");
    await act(async () => {
      await result.current.tick.mutateAsync({
        item: MILK,
        checked: true,
      });
    });
    expect(pendingTicks("user_1")).toEqual([{ planId: 7, foodId: 11, checked: true }]);
    expect(client.getQueryData<typeof LIST>(keys.shopping(7))?.items[0]?.checked).toBe(true);
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("offline"));

    // Back online: the sync sends it.
    function Sync() {
      useOfflineSync();
      return null;
    }
    render(<Sync />, { wrapper });
    online = true;
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => expect(pendingTicks("user_1")).toEqual([]));
    expect(patches).toEqual(['/plans/7/shopping/11 {"checked":true}']);
    expect(toast.success).toHaveBeenCalledWith("Shopping list synced");
  });
});
