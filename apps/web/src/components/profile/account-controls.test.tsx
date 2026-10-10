import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/components/providers";

import { AccountControls } from "./account-controls";

const clerk = vi.hoisted(() => ({
  deleteUser: vi.fn<() => Promise<void>>(),
  signOut: vi.fn<(options: { redirectUrl: string }) => Promise<void>>(),
}));

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => "t" }),
  useUser: () => ({ user: { delete: clerk.deleteUser } }),
  useClerk: () => ({ signOut: clerk.signOut }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function deleteViaUi() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 204 })),
  );
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <AccountControls />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText('Type "delete" to confirm'), {
    target: { value: "delete" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));
}

describe("AccountControls", () => {
  it("deletes the sign-in, then leaves with a full page load", async () => {
    // Clerk's signOut() is a no-op once the user (and so every session) is deleted.
    const replace = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace });
    clerk.deleteUser.mockResolvedValue();
    deleteViaUi();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(clerk.deleteUser).toHaveBeenCalled();
    expect(clerk.signOut).not.toHaveBeenCalled();
  });

  it("still signs out when the identity provider refuses to delete the sign-in", async () => {
    clerk.deleteUser.mockRejectedValue(new Error("reverification required"));
    deleteViaUi();

    await waitFor(() => expect(clerk.signOut).toHaveBeenCalledWith({ redirectUrl: "/" }));
  });
});
