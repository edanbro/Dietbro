import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Me } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";
import { makePlan, ME } from "@/test/fixtures";
import { calls as nav, resetNavigation } from "@/test/navigation";

import { resumeAt, SetupWizard } from "./setup-wizard";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const fresh: Me = {
  ...ME,
  setup_complete: false,
  profile: {
    has_goals: false,
    has_body: false,
    has_allergies: false,
    has_preferences: false,
    pantry_items: 0,
    expiring_soon: 0,
  },
  region: { ...ME.region, saved: false },
};

beforeEach(() => resetNavigation("/setup"));
afterEach(() => vi.unstubAllGlobals());

describe("resumeAt", () => {
  it("starts at the first required step not done", () => {
    expect(resumeAt(fresh)).toBe(0); // region
    const regionDone = { ...fresh, region: { ...fresh.region, saved: true } };
    expect(resumeAt(regionDone)).toBe(2); // goals: the body step is optional
    const allButPrefs = {
      ...regionDone,
      profile: { ...fresh.profile, has_goals: true, has_allergies: true },
    };
    expect(resumeAt(allButPrefs)).toBe(4);
    expect(resumeAt(ME)).toBe(5); // all done: the kitchen step, to make the first plan
  });
});

describe("SetupWizard", () => {
  it("resumes where it was left", async () => {
    mockApi({
      "GET /me": json({ ...fresh, region: { ...fresh.region, saved: true } }),
      "GET /me/goals": json(null),
      "GET /me/body": json(null),
    });
    renderWithClient(<SetupWizard />);
    expect(await screen.findByRole("heading", { name: "Your goals" })).toBeInTheDocument();
    expect(screen.getByText("Step 3 of 6")).toBeInTheDocument();
  });

  it("ends by planning the first week", async () => {
    const calls = mockApi({
      "GET /me": json(ME),
      "GET /pantry": json([]),
      "GET /plans/current": json(null),
      "POST /plans": json(makePlan(), 201),
    });
    renderWithClient(<SetupWizard />);

    fireEvent.click(await screen.findByRole("button", { name: "Plan my first week" }));

    await waitFor(() => expect(nav.push).toContain("/plan"));
    expect(calls.some((c) => c.method === "POST" && c.path === "/plans")).toBe(true);
  });

  it("just finishes when a plan exists", async () => {
    mockApi({
      "GET /me": json(ME),
      "GET /pantry": json([]),
      "GET /plans/current": json(makePlan()),
    });
    renderWithClient(<SetupWizard />);
    fireEvent.click(await screen.findByRole("button", { name: "Go to my plan" }));
    expect(nav.push).toContain("/plan");
  });
});
