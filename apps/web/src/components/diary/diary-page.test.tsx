import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Diary, DiaryDay } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";

import { DiaryPage, eatenText } from "./diary-page";
import { WeightChart } from "./weight-chart";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

afterEach(() => vi.unstubAllGlobals());

const day = (date: string, kcal: number, status: DiaryDay["status"]): DiaryDay => ({
  date,
  eaten: { kcal, protein_g: 0, fat_g: 0, carbs_g: 0 },
  logged: kcal
    ? [
        {
          date,
          slot: "lunch",
          kind: "off_plan",
          description: "Toasted sandwich",
          kcal,
          estimated: true,
        },
      ]
    : [],
  planned_kcal: 2000,
  status,
});

const DIARY: Diary = {
  days: [
    day("2026-10-12", 0, null),
    day("2026-10-13", 1900, "on"),
    day("2026-10-14", 600, "under"),
  ],
  today: "2026-10-14",
  kcal_min: 1800,
  kcal_max: 2200,
  protein_g_min: 90,
  logged_days: 1,
  on_target_days: 1,
};

describe("eatenText", () => {
  it("states the goal band when there is one", () => {
    expect(eatenText(1450, 1800, 2200)).toBe("Eaten 1,450 of 1,800–2,200 kcal");
    expect(eatenText(1450, null, null)).toBe("Eaten 1,450 kcal");
  });
});

describe("DiaryPage", () => {
  it("shows today, the streak and each day newest first", async () => {
    mockApi({ "GET /diary": json(DIARY), "GET /me/weights": json([]) });
    renderWithClient(<DiaryPage />);

    expect(await screen.findByText(/Eaten 600 of 1,800–2,200 kcal today/)).toBeInTheDocument();
    const days = within(screen.getByRole("region", { name: "Days" })).getAllByRole("listitem");
    expect(days[0]).toHaveTextContent("Today");
    expect(days[1]).toHaveTextContent("On target");
    expect(days[2]).toHaveTextContent("Nothing logged");

    fireEvent.click(within(days[1]!).getByRole("button"));
    expect(days[1]).toHaveTextContent("Lunch: Toasted sandwich");
  });

  it("saves today's weight", async () => {
    const calls = mockApi({
      "GET /diary": json(DIARY),
      "GET /me/weights": json([]),
      "PUT /me/weights": json({ measured_on: "2026-10-14", weight_kg: 72.4 }),
    });
    renderWithClient(<DiaryPage />);

    fireEvent.change(await screen.findByLabelText("Today (kg)"), { target: { value: "72,4" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toMatchObject({ weight_kg: 72.4 });
  });
});

describe("WeightChart", () => {
  it("summarises the trend", () => {
    renderWithClient(
      <WeightChart
        weights={[
          { measured_on: "2026-10-01", weight_kg: 80 },
          { measured_on: "2026-10-14", weight_kg: 78.5 },
        ]}
      />,
    );
    expect(screen.getByRole("img")).toHaveAccessibleName(
      expect.stringContaining("Down 1.5 kg") as unknown as string,
    );
  });

  it("asks for more weigh-ins first", () => {
    renderWithClient(<WeightChart weights={[]} />);
    expect(screen.getByText(/couple of weigh-ins/)).toBeInTheDocument();
  });
});
