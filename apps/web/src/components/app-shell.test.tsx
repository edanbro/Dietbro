import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";
import { ME } from "@/test/fixtures";
import { resetNavigation } from "@/test/navigation";

import { AppShell } from "./app-shell";

vi.mock("@clerk/nextjs", () => ({
  UserButton: () => null,
  useAuth: () => ({ getToken: async () => "t" }),
}));
vi.mock("next/navigation", () => import("@/test/navigation"));

beforeEach(() => {
  resetNavigation("/");
  mockApi({ "GET /me": json(ME) });
});
afterEach(() => vi.unstubAllGlobals());

const render = renderWithClient;

describe("AppShell", () => {
  it("puts Plan first and Chat next in the bottom nav, and the logo opens the plan", () => {
    render(<AppShell>content</AppShell>);

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((a) => [a.textContent, a.getAttribute("href")]),
    ).toEqual([
      ["Plan", "/plan"],
      ["Chat", "/chat"],
      ["Pantry", "/pantry"],
      ["Profile", "/profile"],
    ]);
    expect(screen.getByRole("link", { name: "Mealwright" })).toHaveAttribute("href", "/plan");
  });

  it.each([
    ["/plan", "Plan"],
    ["/plan/shopping", "Plan"],
    ["/chat", "Chat"],
    ["/pantry", "Pantry"],
    ["/profile", "Profile"],
  ])("marks %s as %s", (path, label) => {
    resetNavigation(path);
    render(<AppShell>content</AppShell>);

    const current = screen.getAllByRole("link").filter((a) => a.getAttribute("aria-current"));
    expect(current.map((a) => a.textContent)).toEqual([label]);
  });

  it("marks nothing on a recipe page", () => {
    resetNavigation("/recipes/5");
    render(<AppShell>content</AppShell>);

    expect(screen.getAllByRole("link").filter((a) => a.getAttribute("aria-current"))).toEqual([]);
  });

  it("badges the Pantry tab with how much food expires soon", async () => {
    mockApi({ "GET /me": json({ ...ME, profile: { ...ME.profile, expiring_soon: 3 } }) });
    render(<AppShell>content</AppShell>);

    const pantry = await screen.findByRole("link", { name: "Pantry, 3 expiring soon" });
    expect(pantry).toHaveTextContent("3");
  });
});
