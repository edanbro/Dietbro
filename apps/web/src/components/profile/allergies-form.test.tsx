import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/components/providers";

import { AllergiesForm } from "./allergies-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

afterEach(() => vi.unstubAllGlobals());

describe("AllergiesForm", () => {
  it("names checkboxes by their labels and saves the chosen allergens", async () => {
    const puts: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (req: Request) => {
        const path = new URL(req.url).pathname;
        if (path === "/allergens") {
          return Response.json([
            { code: "peanuts", label: "Peanuts" },
            { code: "milk", label: "Milk" },
          ]);
        }
        if (req.method === "PUT") {
          puts.push(await req.json());
          return Response.json({ allergens: ["peanuts"], avoid_food_ids: [], avoid_foods: [] });
        }
        return Response.json(null);
      }),
    );
    const onSaved = vi.fn();
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <AllergiesForm onSaved={onSaved} />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("checkbox", { name: "Peanuts" }));
    fireEvent.click(screen.getByRole("button", { name: "Save allergies" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(puts).toEqual([{ allergens: ["peanuts"], avoid_food_ids: [] }]);
  });

  it("offers a one-tap 'no allergies' save", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json([])),
    );
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <AllergiesForm />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("button", { name: "I have no allergies" })).toBeInTheDocument();
  });
});
