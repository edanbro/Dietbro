import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";
import { ME } from "@/test/fixtures";

import { RegionForm } from "./region-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));
vi.mock("@/lib/region", async (original) => ({
  ...(await original<typeof import("@/lib/region")>()),
  guessRegion: () => ({ country: "IE", timezone: "Europe/Dublin", locale: "en-IE" }),
}));

const REGIONS = [
  { country: "IE", name: "Ireland", currency: "EUR" },
  { country: "GB", name: "United Kingdom", currency: "GBP" },
];
const IRELAND = {
  country: "IE",
  name: "Ireland",
  currency: "EUR",
  locale: "en-IE",
  timezone: "Europe/Dublin",
  saved: true,
};

afterEach(() => vi.unstubAllGlobals());

describe("RegionForm", () => {
  let calls: ReturnType<typeof mockApi>;
  beforeEach(() => {
    calls = mockApi({
      "GET /me": json({ ...ME, region: { ...ME.region, saved: false } }),
      "GET /regions": json(REGIONS),
      "PUT /me/region": json(IRELAND),
    });
  });

  it("offers the browser's guess and saves it with the time zone", async () => {
    renderWithClient(<RegionForm />);

    await waitFor(() => expect(screen.getByLabelText("Country")).toHaveValue("IE"));
    expect(screen.getByText(/estimated for Ireland/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save region" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      country: "IE",
      timezone: "Europe/Dublin",
      locale: "en-IE",
    });
  });

  it("lets the user pick another country", async () => {
    renderWithClient(<RegionForm />);

    await waitFor(() => expect(screen.getByLabelText("Country")).toHaveValue("IE"));
    fireEvent.change(screen.getByLabelText("Country"), { target: { value: "GB" } });

    expect(screen.getByText(/estimated for United Kingdom/)).toBeInTheDocument();
  });
});
