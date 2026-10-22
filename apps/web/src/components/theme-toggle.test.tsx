import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_SCRIPT } from "@/lib/theme";

import { ThemeToggle } from "./theme-toggle";

function prefersDark(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: dark, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
}

const root = () => document.documentElement.classList;

beforeEach(() => {
  localStorage.clear();
  root().remove("dark", "light");
  prefersDark(false);
});
afterEach(() => vi.unstubAllGlobals());

describe("ThemeToggle", () => {
  it("switches and remembers the theme", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("radio", { name: "System" })).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(root().contains("dark")).toBe(true);
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(screen.getByRole("radio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("radio", { name: "System" }));
    expect(root().contains("light")).toBe(true); // the device is light
    expect(localStorage.getItem("theme")).toBeNull();
  });
});

describe("THEME_SCRIPT", () => {
  it.each([
    [null, true, "dark"],
    [null, false, "light"],
    ["light", true, "light"],
    ["dark", false, "dark"],
  ])("stored %s, device dark %s -> %s", (stored, dark, expected) => {
    if (stored) localStorage.setItem("theme", stored);
    prefersDark(dark);
    new Function(THEME_SCRIPT)();
    expect(root().contains(expected)).toBe(true);
  });

  it("follows the device when it switches, on pages without a toggle", () => {
    let dark = false;
    let onChange: () => void = () => undefined;
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        get matches() {
          return dark;
        },
        addEventListener: (_: string, f: () => void) => {
          onChange = f;
        },
      })),
    );
    new Function(THEME_SCRIPT)();
    expect(root().contains("light")).toBe(true);
    dark = true;
    onChange();
    expect(root().contains("dark")).toBe(true);
  });
});
