import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetNavigation } from "@/test/navigation";

import { AppShell } from "./app-shell";

vi.mock("@clerk/nextjs", () => ({ UserButton: () => null }));
vi.mock("next/navigation", () => import("@/test/navigation"));

beforeEach(() => resetNavigation("/"));

describe("AppShell", () => {
  it("puts Plan first in the bottom nav and the logo opens the plan", () => {
    render(<AppShell>content</AppShell>);

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((a) => [a.textContent, a.getAttribute("href")]),
    ).toEqual([
      ["Plan", "/plan"],
      ["Pantry", "/pantry"],
      ["Profile", "/profile"],
    ]);
    expect(screen.getByRole("link", { name: "Larder" })).toHaveAttribute("href", "/plan");
  });

  it.each([
    ["/plan", "Plan"],
    ["/plan/shopping", "Plan"],
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
});
