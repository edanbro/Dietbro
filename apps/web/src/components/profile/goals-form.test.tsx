import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/components/providers";

import { GoalsForm } from "./goals-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

type Handler = (request: Request) => Response | Promise<Response>;

function mockApi(handler: Handler) {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      calls.push(input);
      return handler(input);
    }),
  );
  return calls;
}

function renderForm(onSaved = vi.fn()) {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <GoalsForm onSaved={onSaved} />
    </QueryClientProvider>,
  );
  return onSaved;
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe("GoalsForm", () => {
  it("shows the API's reasons when targets are refused", async () => {
    mockApi((req) =>
      req.method === "PUT"
        ? Response.json(
            { detail: ["daily minimum is below your calorie floor (1200 kcal)"] },
            { status: 400 },
          )
        : Response.json(null),
    );
    const onSaved = renderForm();

    fill("Min kcal / day", "900");
    fill("Max kcal / day", "1100");
    fireEvent.click(screen.getByRole("button", { name: "Save goals" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("below your calorie floor");
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("sends the bearer token and the entered values", async () => {
    const calls = mockApi((req) =>
      req.method === "PUT"
        ? Response.json({ kcal_min: 1800, kcal_max: 2200, currency: "GBP", updated_at: "x" })
        : Response.json(null),
    );
    const onSaved = renderForm();

    fill("Min kcal / day", "1800");
    fill("Max kcal / day", "2200");
    fill("Weekly food budget (optional)", "60.50");
    fireEvent.click(screen.getByRole("button", { name: "Save goals" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.headers.get("Authorization")).toBe("Bearer test-token");
    const body = await put?.json();
    expect(body).toMatchObject({ kcal_min: 1800, kcal_max: 2200, weekly_budget_minor: 6050 });
  });
});
