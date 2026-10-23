import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { PantryPage } from "./pantry-page";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));

afterEach(() => vi.unstubAllGlobals());

const item = (id: number, grams: number) => ({
  id,
  food: { id: id + 100, description: "Rice, white", category: null, kcal: 360, kind: "food", source: "usda" },
  grams,
  quantity: grams,
  unit: "g",
  approx: false,
  expires_on: null,
  source: "manual",
  created_at: "2026-10-01T09:00:00Z",
  storage: null,
});

describe("PantryPage", () => {
  it("asks what can be cooked once there's food in the pantry", async () => {
    mockApi({ "GET /pantry": json([item(1, 500)]) });
    renderWithClient(<PantryPage />);

    expect(await screen.findByRole("link", { name: "What can I cook?" })).toHaveAttribute(
      "href",
      "/recipes?pantry=1",
    );
  });

  it("doesn't ask with an empty pantry", async () => {
    mockApi({ "GET /pantry": json([]) });
    renderWithClient(<PantryPage />);

    expect(await screen.findByText("Your pantry is empty")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "What can I cook?" })).not.toBeInTheDocument();
  });
});
