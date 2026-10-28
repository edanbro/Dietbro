import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Diary, DiaryDay } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";
import { ME } from "@/test/fixtures";
import { resetNavigation } from "@/test/navigation";

import { DiaryPage, dayRows, eatenText } from "./diary-page";
import { WeightChart } from "./weight-chart";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => resetNavigation("/diary"));

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

describe("dayRows", () => {
  it("folds runs of empty days into one row, but never today or a planned day", () => {
    const empty = (date: string): DiaryDay => ({ ...day(date, 0, null), planned_kcal: null });
    const days = [
      day("2026-10-14", 600, "under"),
      empty("2026-10-13"),
      empty("2026-10-12"),
      empty("2026-10-11"),
      day("2026-10-10", 0, null), // planned: its own row
      empty("2026-10-09"), // a run of one stays a day
    ];
    expect(dayRows(days, "2026-10-14").map((r) => (r.kind === "day" ? r.day.date : r))).toEqual([
      "2026-10-14",
      { kind: "empty", from: "2026-10-11", to: "2026-10-13" },
      "2026-10-10",
      "2026-10-09",
    ]);
    expect(dayRows([empty("2026-10-14"), empty("2026-10-13")], "2026-10-14")).toHaveLength(2);
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

  it("removes food logged by mistake", async () => {
    const today = day("2026-10-14", 600, "under");
    today.logged[0] = { ...today.logged[0]!, id: 5 };
    const calls = mockApi({
      "GET /diary": json({ ...DIARY, days: [today] }),
      "GET /me/weights": json([]),
      "DELETE /diary/logs/5": json({ outcome: null }),
    });
    renderWithClient(<DiaryPage />);

    const [row] = within(await screen.findByRole("region", { name: "Days" })).getAllByRole(
      "listitem",
    );
    fireEvent.click(within(row!).getAllByRole("button")[0]!);
    fireEvent.click(within(row!).getByRole("button", { name: "Remove Toasted sandwich" }));

    await waitFor(() =>
      expect(calls.some((c) => c.method === "DELETE" && c.path === "/diary/logs/5")).toBe(true),
    );
  });

  it("opens quick-add for the meal a link asks for", async () => {
    resetNavigation("/diary?add=lunch");
    mockApi({ "GET /diary": json(DIARY), "GET /me/weights": json([]) });
    renderWithClient(<DiaryPage />);

    expect(await screen.findByRole("form", { name: "Add food you ate" })).toBeInTheDocument();
    expect(screen.getByLabelText("Meal")).toHaveValue("lunch");
  });

  it("shows the last week, with the rest on request", async () => {
    const days = Array.from({ length: 14 }, (_, i) =>
      day(`2026-10-${String(i + 1).padStart(2, "0")}`, 0, null),
    );
    mockApi({
      "GET /diary": json({ ...DIARY, days, today: "2026-10-14" }),
      "GET /me/weights": json([]),
    });
    renderWithClient(<DiaryPage />);

    const region = await screen.findByRole("region", { name: "Days" });
    expect(within(region).getAllByRole("listitem")).toHaveLength(7);
    fireEvent.click(within(region).getByRole("button", { name: "Show all 14 days" }));
    expect(within(region).getAllByRole("listitem")).toHaveLength(14);
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

  it("takes pounds in US units, and says when a weight can't be right", async () => {
    const calls = mockApi({
      "GET /me": json({ ...ME, region: { ...ME.region, country: "US", units: "us" } }),
      "GET /diary": json(DIARY),
      "GET /me/weights": json([{ measured_on: "2026-10-01", weight_kg: 80 }]),
      "PUT /me/weights": json({ measured_on: "2026-10-14", weight_kg: 72.6 }),
    });
    renderWithClient(<DiaryPage />);

    const input = await screen.findByLabelText("Today (lb)");
    expect(await screen.findByText("176.4 lb")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "16" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Enter your weight in pounds/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);

    fireEvent.change(input, { target: { value: "160" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ weight_kg: 72.6 });
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
