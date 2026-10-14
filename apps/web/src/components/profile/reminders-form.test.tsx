import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { keyBytes, RemindersForm } from "./reminders-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

afterEach(() => vi.unstubAllGlobals());

describe("keyBytes", () => {
  it("decodes base64url without padding", () => {
    expect(Array.from(keyBytes("AQID_-8"))).toEqual([1, 2, 3, 255, 239]);
  });
});

describe("RemindersForm", () => {
  it("explains when the browser can't show reminders", () => {
    mockApi({ "GET /me/push": json({ enabled: true, public_key: "k", subscribed: 0 }) });
    renderWithClient(<RemindersForm />); // jsdom has no PushManager
    expect(screen.getByText(/can't show reminders/)).toBeInTheDocument();
  });

  it("offers to turn reminders on where push works", async () => {
    vi.stubGlobal("PushManager", function PushManager() {});
    vi.stubGlobal("Notification", { requestPermission: vi.fn() });
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { getRegistration: async () => undefined, ready: new Promise(() => {}) },
    });
    mockApi({ "GET /me/push": json({ enabled: true, public_key: "k", subscribed: 2 }) });
    renderWithClient(<RemindersForm />);
    const button = await screen.findByRole("button", { name: "Turn on reminders" });
    await waitFor(() => expect(button).toBeEnabled());
    expect(screen.getByText("Also on in 2 other browsers.")).toBeInTheDocument();
  });
});
