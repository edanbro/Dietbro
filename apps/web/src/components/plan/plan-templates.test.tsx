import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type PlanChange, useCreatePlan } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";
import { makePlan } from "@/test/fixtures";

import { CopyDay, RepeatChoices, SaveTemplate } from "./plan-templates";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => vi.unstubAllGlobals());

const TEMPLATES = [
  { id: 3, name: "Busy week", created_at: "2026-10-01T09:00:00Z", meals: 21, recipes: ["Stew"] },
  { id: 4, name: "Light week", created_at: "2026-10-02T09:00:00Z", meals: 14, recipes: [] },
];

function Choices({ onCreated }: { onCreated: () => void }) {
  const create = useCreatePlan();
  return <RepeatChoices today="2026-10-23" create={create} onCreated={onCreated} />;
}

describe("RepeatChoices", () => {
  it("repeats last week's days", async () => {
    const calls = mockApi({
      "GET /me/templates": json([]),
      "POST /plans": json(makePlan(), 201),
    });
    const onCreated = vi.fn();
    renderWithClient(<Choices onCreated={onCreated} />);

    fireEvent.click(screen.getByRole("button", { name: "Repeat last week" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ repeat_from: "2026-10-16" });
    expect(screen.queryByLabelText("Template")).not.toBeInTheDocument(); // none saved
  });

  it("plans from a chosen template", async () => {
    const calls = mockApi({
      "GET /me/templates": json(TEMPLATES),
      "POST /plans": json(makePlan(), 201),
    });
    renderWithClient(<Choices onCreated={() => undefined} />);

    fireEvent.change(await screen.findByLabelText("Template"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Use template" }));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ template_id: 4 });
  });
});

describe("SaveTemplate", () => {
  it("names this week and saves it", async () => {
    const plan = makePlan();
    const calls = mockApi({ "POST /me/templates": json({ ...TEMPLATES[0], name: "Mine" }, 201) });
    renderWithClient(<SaveTemplate plan={plan} />);

    fireEvent.click(screen.getByRole("button", { name: "Save as template" }));
    const form = screen.getByRole("form", { name: "Save as template" });
    fireEvent.change(within(form).getByLabelText("Template name"), { target: { value: " Mine " } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(screen.queryByRole("form", { name: "Save as template" })).not.toBeInTheDocument(),
    );
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "Mine",
      start: plan.start,
    });
  });
});

describe("CopyDay", () => {
  it("shows the other day's meals and swaps the open slots to them", async () => {
    const plan = makePlan();
    const day = { ...plan.days[1]! };
    day.meals = day.meals.map((m) => (m.slot === "breakfast" ? { ...m, status: "eaten" } : m));
    mockApi({
      "GET /plans/meals": json([
        {
          slot: "breakfast",
          recipe: { id: 70, name: "Toast", category: null, cuisine: null, image_url: null },
        },
        {
          slot: "dinner",
          recipe: { id: 71, name: "Irish stew", category: null, cuisine: null, image_url: null },
        },
      ]),
    });
    const onReplan = vi.fn<(changes: PlanChange[]) => Promise<unknown>>(async () => undefined);
    renderWithClient(
      <CopyDay day={day} today={plan.days[0]!.date} busy={false} onReplan={onReplan} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Copy another day" }));
    expect(await screen.findByText("Irish stew")).toBeInTheDocument();
    expect(screen.queryByText("Toast")).not.toBeInTheDocument(); // breakfast was eaten here
    fireEvent.click(screen.getByRole("button", { name: "Use these meals" }));

    await waitFor(() => expect(onReplan).toHaveBeenCalled());
    expect(onReplan.mock.calls[0]![0]).toEqual([
      { intent: "swap", when: { date: day.date, slot: "dinner" }, recipe_id: 71 },
    ]);
  });
});
