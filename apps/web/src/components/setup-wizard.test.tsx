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
    expect(resumeAt({ ...fresh, consented: false })).toBe(0); // consent
    expect(resumeAt(fresh)).toBe(1); // region
    const regionDone = { ...fresh, region: { ...fresh.region, saved: true } };
    expect(resumeAt(regionDone)).toBe(3); // goals: the body step is optional
    const allButPrefs = {
      ...regionDone,
      profile: { ...fresh.profile, has_goals: true, has_allergies: true },
    };
    expect(resumeAt(allButPrefs)).toBe(5);
    expect(resumeAt(ME)).toBe(6); // all done: the kitchen step, to make the first plan
    // Set up before consent was asked for: consent first, whatever else is done.
    expect(resumeAt({ ...ME, consented: false, setup_complete: false })).toBe(0);
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
    expect(screen.getByText("Step 4 of 7")).toBeInTheDocument();
  });

  it("asks for the terms and the health-data consent separately, then moves on", async () => {
    const calls = mockApi({
      "GET /me": json({ ...fresh, consented: false }),
      "PUT /me/consent": json(fresh),
      "GET /regions": json([]),
    });
    renderWithClient(<SetupWizard />);

    const agree = await screen.findByRole("button", { name: "Agree and continue" });
    expect(screen.getByRole("heading", { name: "Before you start" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
    expect(screen.getByRole("link", { name: "Privacy policy" })).toHaveAttribute(
      "href",
      "/privacy",
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /18 or over/ }));
    expect(agree).toBeDisabled(); // the terms alone aren't consent to keep health data
    fireEvent.click(screen.getByRole("checkbox", { name: /health information/ }));
    fireEvent.click(agree);

    expect(await screen.findByRole("heading", { name: "Where are you?" })).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT" && c.path === "/me/consent");
    expect(put?.body).toEqual({ terms: true, health_data: true });
  });

  it("sends an account set up before consent was asked for back to its plan", async () => {
    mockApi({
      "GET /me": json({ ...ME, consented: false, setup_complete: false }),
      "PUT /me/consent": json(ME),
    });
    renderWithClient(<SetupWizard />);

    fireEvent.click(await screen.findByRole("checkbox", { name: /18 or over/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /health information/ }));
    fireEvent.click(screen.getByRole("button", { name: "Agree and continue" }));

    await waitFor(() => expect(nav.push).toContain("/plan"));
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
