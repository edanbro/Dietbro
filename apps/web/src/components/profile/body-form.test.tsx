import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";
import { ME } from "@/test/fixtures";

import { BodyForm } from "./body-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn() }) }));

const SAVED = {
  sex: "male",
  age: 40,
  height_cm: 178,
  weight_kg: 80,
  activity: "light",
  tdee_kcal: 2500,
};

afterEach(() => vi.unstubAllGlobals());

describe("BodyForm", () => {
  it("takes centimetres and kilograms", async () => {
    const calls = mockApi({
      "GET /me": json(ME),
      "GET /me/body": json(SAVED),
      "PUT /me/body": json(SAVED),
    });
    renderWithClient(<BodyForm />);

    await waitFor(() => expect(screen.getByLabelText("Height (cm)")).toHaveValue(178));
    fireEvent.change(screen.getByLabelText("Weight (kg)"), { target: { value: "78.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
      height_cm: 178,
      weight_kg: 78.5,
    });
  });

  it("takes feet, inches and pounds in US units, and saves them as metric", async () => {
    const calls = mockApi({
      "GET /me": json({ ...ME, region: { ...ME.region, country: "US", units: "us" } }),
      "GET /me/body": json(SAVED),
      "PUT /me/body": json(SAVED),
    });
    renderWithClient(<BodyForm />);

    await waitFor(() => expect(screen.getByLabelText("Height (ft)")).toHaveValue(5));
    expect(screen.getByLabelText("and inches")).toHaveValue(10);
    expect(screen.getByLabelText("Weight (lb)")).toHaveValue(176.4);
    expect(screen.queryByLabelText("Height (cm)")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("and inches"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("Weight (lb)"), { target: { value: "170" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
      height_cm: 180.3,
      weight_kg: 77.1,
    });
  });
});
