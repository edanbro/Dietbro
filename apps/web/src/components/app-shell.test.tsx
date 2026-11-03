import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";
import { ME } from "@/test/fixtures";
import { resetNavigation } from "@/test/navigation";

import { AppShell } from "./app-shell";

const clerk = vi.hoisted(() => ({ metadata: {} as Record<string, unknown> }));
vi.mock("@clerk/nextjs", () => ({
  UserButton: () => <button type="button">Account menu</button>,
  SignOutButton: ({ children }: { children: React.ReactNode }) => children,
  useUser: () => ({ user: { publicMetadata: clerk.metadata } }),
  useAuth: () => ({ getToken: async () => "t" }),
}));
vi.mock("next/navigation", () => import("@/test/navigation"));

beforeEach(() => {
  clerk.metadata = {};
  resetNavigation("/");
  mockApi({ "GET /me": json(ME) });
});
afterEach(() => vi.unstubAllGlobals());

const render = renderWithClient;

describe("AppShell", () => {
  it("has the everyday places in the bottom nav, Plan and Shopping first; the logo opens the plan", () => {
    render(<AppShell>content</AppShell>);

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((a) => [a.textContent, a.getAttribute("href")]),
    ).toEqual([
      ["Plan", "/plan"],
      ["Shopping", "/plan/shopping"],
      ["Recipes", "/recipes"],
      ["Pantry", "/pantry"],
      ["Diary", "/diary"],
    ]);
    for (const logo of screen.getAllByRole("link", { name: "Mealwright" })) {
      expect(logo).toHaveAttribute("href", "/plan"); // header (phone) and rail (desktop)
    }
  });

  it.each([
    ["/plan", "Plan"],
    ["/plan/shopping", "Shopping"],
    ["/recipes/12", "Recipes"],
    ["/pantry", "Pantry"],
    ["/diary", "Diary"],
    ["/recap", "Diary"],
  ])("marks %s as %s", (path, label) => {
    resetNavigation(path);
    render(<AppShell>content</AppShell>);

    const nav = screen.getByRole("navigation", { name: "Main" });
    const current = within(nav)
      .getAllByRole("link")
      .filter((a) => a.getAttribute("aria-current"));
    expect(current.map((a) => a.textContent)).toEqual([label]);
  });

  it("starts with a skip link to the page content", () => {
    render(<AppShell>content</AppShell>);

    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveTextContent("Skip to content");
    expect(links[0]).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });

  it("keeps the profile out of the tabs: in the phone's header and the desktop rail", () => {
    resetNavigation("/profile");
    render(<AppShell>content</AppShell>);

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").filter((a) => a.getAttribute("aria-current"))).toEqual(
      [],
    );
    const rail = screen.getByRole("navigation", { name: "Sidebar" });
    expect(within(rail).getByRole("link", { name: "Profile" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Profile" })).toHaveAttribute(
      "href",
      "/profile",
    );
  });

  it("shows Clerk's account menu to a normal account", () => {
    render(<AppShell>content</AppShell>);

    expect(screen.getAllByRole("button", { name: "Account menu" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });

  it("gives the demo account a plain sign-out, so no visitor sees its email", () => {
    clerk.metadata = { demo: true };
    render(<AppShell>content</AppShell>);

    expect(screen.queryByRole("button", { name: "Account menu" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Sign out" })).toHaveLength(2); // header and rail
  });

  it("tells the demo's visitors that what they enter is shared", () => {
    render(<AppShell>content</AppShell>);
    expect(screen.queryByText(/Shared demo/)).not.toBeInTheDocument();

    clerk.metadata = { demo: true };
    render(<AppShell>content</AppShell>);
    expect(screen.getByText(/Shared demo: anyone can see what's entered here/)).toBeInTheDocument();
  });

  it("badges the Pantry tab with how much food expires soon", async () => {
    mockApi({ "GET /me": json({ ...ME, profile: { ...ME.profile, expiring_soon: 3 } }) });
    render(<AppShell>content</AppShell>);

    const pantry = await screen.findByRole("link", { name: "Pantry, 3 expiring soon" });
    expect(pantry).toHaveTextContent("3");
  });
});
