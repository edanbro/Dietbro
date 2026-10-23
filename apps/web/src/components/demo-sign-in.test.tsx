import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { calls, resetNavigation } from "@/test/navigation";

import { DemoSignIn } from "./demo-sign-in";

const auth = { isLoaded: true, isSignedIn: false };
const signIn = {
  ticket: vi.fn(async () => ({ error: null })),
  finalize: vi.fn(async ({ navigate }: { navigate: () => void }) => {
    navigate();
    return { error: null };
  }),
};
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth, useSignIn: () => ({ signIn }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  auth.isSignedIn = false;
});

describe("DemoSignIn", () => {
  it("signs in with the ticket and opens the plan", async () => {
    resetNavigation("/demo");
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ticket: "t-1" })));
    render(<DemoSignIn />);
    await waitFor(() => expect(calls.replace).toContain("/plan"));
    expect(signIn.ticket).toHaveBeenCalledWith({ ticket: "t-1" });
  });

  it("says why when the demo is off", async () => {
    resetNavigation("/demo");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: ["The demo isn't set up here."] }, { status: 404 })),
    );
    render(<DemoSignIn />);
    expect(await screen.findByRole("alert")).toHaveTextContent("isn't set up");
  });

  it("sends a signed-in visitor to their own plan", async () => {
    resetNavigation("/demo");
    auth.isSignedIn = true;
    render(<DemoSignIn />);
    await waitFor(() => expect(calls.replace).toContain("/plan"));
    expect(signIn.ticket).not.toHaveBeenCalled();
  });
});
