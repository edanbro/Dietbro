import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { calls, resetNavigation } from "@/test/navigation";

import { ProfileIndex } from "./profile-index";

vi.mock("next/navigation", () => import("@/test/navigation"));

beforeEach(() => {
  resetNavigation("/profile");
  window.location.hash = "";
});

describe("ProfileIndex", () => {
  it("lists every section as a link to its own page, grouped", () => {
    render(<ProfileIndex />);

    const eating = screen.getByRole("region", { name: "Eating" });
    expect(within(eating).getByRole("link", { name: /^Goals/ })).toHaveAttribute(
      "href",
      "/profile/goals",
    );
    expect(within(eating).getByRole("link", { name: /^Allergies/ })).toBeInTheDocument();
    const app = screen.getByRole("region", { name: "App" });
    expect(within(app).getByRole("link", { name: /^Your data/ })).toHaveAttribute(
      "href",
      "/profile/account",
    );
    expect(screen.getAllByRole("link")).toHaveLength(12);
  });

  it("opens the section an old link to the long page pointed at", () => {
    window.location.hash = "#meals";
    render(<ProfileIndex />);

    expect(calls.replace).toEqual(["/profile/meals"]);
  });
});
