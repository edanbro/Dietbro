import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { TemplatesForm } from "./templates-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => vi.unstubAllGlobals());

const BUSY = {
  id: 3,
  name: "Busy week",
  created_at: "2026-10-01T09:00:00Z",
  meals: 21,
  recipes: ["Irish stew", "Chicken curry"],
};

describe("TemplatesForm", () => {
  it("explains templates when there are none", async () => {
    mockApi({ "GET /me/templates": json([]) });
    renderWithClient(<TemplatesForm />);
    expect(await screen.findByText(/Save a week you liked/)).toBeInTheDocument();
  });

  it("renames and deletes", async () => {
    let list = [BUSY];
    const calls = mockApi({
      "GET /me/templates": () => json(list)(),
      "PATCH /me/templates/3": () => {
        list = [{ ...BUSY, name: "Easy" }];
        return json(list[0])();
      },
      "DELETE /me/templates/3": () => {
        list = [];
        return new Response(null, { status: 204 });
      },
    });
    renderWithClient(<TemplatesForm />);

    const row = within(await screen.findByRole("list", { name: "Templates" }));
    expect(row.getByText("21 meals: Irish stew, Chicken curry")).toBeInTheDocument();

    fireEvent.click(row.getByRole("button", { name: "Rename Busy week" }));
    fireEvent.change(screen.getByLabelText("Template name"), { target: { value: "Easy" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Easy")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Easy" });

    fireEvent.click(screen.getByRole("button", { name: "Delete Easy" }));
    await waitFor(() => expect(screen.getByText(/Save a week you liked/)).toBeInTheDocument());
  });
});
