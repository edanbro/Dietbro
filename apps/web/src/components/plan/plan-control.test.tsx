import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PlanOutcome } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient, type Routes } from "@/test/api";
import { makePlan, ME } from "@/test/fixtures";
import { resetNavigation } from "@/test/navigation";

import { PlanPage } from "./plan-page";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => import("@/test/navigation"));

function setup(routes: Routes) {
  const calls = mockApi({
    "GET /me": json(ME),
    "GET /allergens": json([]),
    "GET /plans/upcoming": json(null),
    ...routes,
  });
  renderWithClient(<PlanPage />);
  return calls;
}

const outcome: PlanOutcome = {
  type: "outcome",
  plan_id: 8,
  version: 2,
  fresh: false,
  results: [
    {
      index: 0,
      intent: "swap",
      date: "2026-10-10",
      slot: "dinner",
      status: "applied",
      message: "Swapped Sat dinner.",
    },
  ],
  changes: [],
  logged: [],
  days: [],
  warnings: [],
  notes: [],
};

beforeEach(() => {
  resetNavigation("/plan");
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 9, 10, 0));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("plan control", () => {
  it("rebuilds a later day in one change, then undoes it", async () => {
    const calls = setup({
      "GET /plans/current": json(makePlan()),
      "POST /plans/replan": json(outcome),
      "POST /plans/8/undo": json(makePlan({ id: 9 })),
    });

    fireEvent.click(await screen.findByRole("tab", { name: "Sat 10 October" }));
    fireEvent.click(await screen.findByRole("button", { name: "Rebuild Sat" }));

    const panel = await screen.findByRole("region", { name: "What changed" });
    const body = calls.find((c) => c.path === "/plans/replan")?.body as {
      changes: { intent: string; when: { slot: string } }[];
    };
    expect(body.changes.map((c) => [c.intent, c.when.slot])).toEqual([
      ["swap", "breakfast"],
      ["swap", "lunch"],
      ["swap", "dinner"],
    ]);

    fireEvent.click(within(panel).getByRole("button", { name: "Undo this change" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Change undone"));
    expect(calls.some((c) => c.path === "/plans/8/undo")).toBe(true);
    expect(screen.queryByRole("region", { name: "What changed" })).not.toBeInTheDocument();
  });

  it("offers no rebuild for today", async () => {
    setup({ "GET /plans/current": json(makePlan()) });
    await screen.findByRole("list", { name: "Meals on Friday 9 October" });
    expect(screen.queryByRole("button", { name: /Rebuild/ })).not.toBeInTheDocument();
  });

  it("plans next week near the end of this one and switches to it", async () => {
    vi.setSystemTime(new Date(2026, 9, 14, 10, 0)); // the plan ends on the 15th
    const next = makePlan({ id: 20, start: "2026-10-16" });
    let upcoming: unknown = null;
    const calls = setup({
      "GET /plans/current": json(makePlan()),
      "GET /plans/upcoming": () => Response.json(upcoming),
      "POST /plans": () => {
        upcoming = next;
        return Response.json(next, { status: 201 });
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Plan next week" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Next week is planned"));
    expect(calls.find((c) => c.path === "/plans" && c.method === "POST")?.body).toMatchObject({
      start: "2026-10-16",
    });
    const toggle = await screen.findByRole("group", { name: "Which week" });
    expect(within(toggle).getByRole("button", { name: "Next week" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("heading", { name: "Next week" })).toBeInTheDocument();
  });
});
