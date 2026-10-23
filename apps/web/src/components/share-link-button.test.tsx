import { fireEvent, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { ShareLinkButton } from "./share-link-button";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() } }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("ShareLinkButton", () => {
  it("copies a public link and offers to stop sharing", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, share: undefined, clipboard: { writeText } });
    const calls = mockApi({
      "POST /share": json({ token: "abc123", path: "/s/abc123" }),
      "DELETE /share/abc123": () => new Response(null, { status: 204 }),
    });
    renderWithClient(
      <ShareLinkButton target={{ kind: "recipe", recipe_id: 7 }} title="Irish stew" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Share" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${location.origin}/s/abc123`));
    expect(calls.find((c) => c.path === "/share")?.body).toEqual({ kind: "recipe", recipe_id: 7 });
    const [, options] = vi.mocked(toast.success).mock.calls[0]!;
    const action = (options as { action: { label: string; onClick: () => void } }).action;
    expect(action.label).toBe("Stop sharing");
    action.onClick();
    await waitFor(() =>
      expect(calls.some((c) => c.method === "DELETE" && c.path === "/share/abc123")).toBe(true),
    );
  });
});

describe("ShareLinkButton for a shopping list", () => {
  it("shares the week's list to tick off together", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, share: undefined, clipboard: { writeText } });
    const calls = mockApi({ "POST /share": json({ token: "list1", path: "/s/list1" }) });
    renderWithClient(
      <ShareLinkButton
        target={{ kind: "list", start: "2026-10-09" }}
        title="Shopping list"
        label="Shop together"
        reach="can tick things off"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Shop together" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${location.origin}/s/list1`));
    expect(calls.find((c) => c.path === "/share")?.body).toEqual({
      kind: "list",
      start: "2026-10-09",
    });
    expect(vi.mocked(toast.success).mock.calls[0]![0]).toBe(
      "Link copied: anyone with it can tick things off",
    );
  });
});
