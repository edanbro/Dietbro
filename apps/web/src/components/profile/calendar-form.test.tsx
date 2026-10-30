import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { CalendarForm, feedUrls } from "./calendar-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() } }));

afterEach(() => vi.unstubAllGlobals());

const TIMES = {
  breakfast: "08:00",
  lunch: "13:00",
  dinner: "19:00",
  snack: "16:00",
  morning_snack: "10:30",
  evening_snack: "21:00",
};

describe("feedUrls", () => {
  it("gives the https, webcal and Google subscribe addresses", () => {
    const urls = feedUrls("/calendar/abc.ics", "https://api.example.com");
    expect(urls.https).toBe("https://api.example.com/calendar/abc.ics");
    expect(urls.webcal).toBe("webcal://api.example.com/calendar/abc.ics");
    expect(urls.google).toBe(
      "https://calendar.google.com/calendar/r?cid=webcal%3A%2F%2Fapi.example.com%2Fcalendar%2Fabc.ics",
    );
  });
});

describe("CalendarForm", () => {
  it("turns the feed on and offers ways to subscribe", async () => {
    const calls = mockApi({
      "GET /me/calendar": json({ enabled: false, path: null, times: TIMES }),
      "POST /me/calendar": json({ enabled: true, path: "/calendar/abc.ics", times: TIMES }),
      "PUT /me/calendar/times": json({
        enabled: true,
        path: "/calendar/abc.ics",
        times: { ...TIMES, dinner: "18:30" },
      }),
    });
    renderWithClient(<CalendarForm />);

    fireEvent.click(await screen.findByRole("button", { name: "Add to my calendar" }));

    const apple = await screen.findByRole("link", { name: "Apple or Outlook" });
    expect(apple.getAttribute("href")).toMatch(/^webcal:\/\/.*\/calendar\/abc\.ics$/);
    expect(screen.getByRole("link", { name: "Google Calendar" })).toHaveAttribute(
      "href",
      expect.stringContaining("calendar.google.com"),
    );
    fireEvent.change(screen.getByLabelText("Dinner"), { target: { value: "18:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save times" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/me/calendar/times")?.body).toEqual({
        ...TIMES,
        dinner: "18:30",
      }),
    );
  });
});
