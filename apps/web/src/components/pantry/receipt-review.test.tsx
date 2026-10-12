import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Receipt, ReceiptLine, ReceiptLinePatch } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient, type Routes } from "@/test/api";
import { BANANA, makeReceipt, MILK, receiptLine } from "@/test/fixtures";
import { calls as nav, resetNavigation } from "@/test/navigation";

import { lineAmount, ReceiptReview, willAdd } from "./receipt-review";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

beforeEach(() => resetNavigation("/pantry/receipts/5"));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

/** A fake of the receipt endpoints: PATCH changes the line, confirm adds what's left. */
function receiptServer(receipt: Receipt = makeReceipt()): Routes {
  const state = structuredClone(receipt);
  const routes: Routes = {
    "GET /pantry/receipts/5": () => Response.json(structuredClone(state)),
    "POST /pantry/receipts/5/confirm": () => {
      const added = state.lines.filter(willAdd);
      state.status = "confirmed";
      added.forEach((l, i) => (l.pantry_item_id = 100 + i));
      return Response.json({
        receipt: state,
        created: added.map((l, i) => ({ id: 100 + i, food: l.food })),
      });
    },
    "DELETE /pantry/receipts/5": () => new Response(null, { status: 204 }),
    "GET /foods/search": json([BANANA]),
    "GET /foods/33": json({
      ...BANANA,
      units: [
        { unit: "g", grams_each: 1 },
        { unit: "medium", grams_each: 118 },
      ],
    }),
    "GET /foods/31": json({
      ...MILK,
      units: [
        { unit: "l", grams_each: 1030 },
        { unit: "g", grams_each: 1 },
      ],
    }),
  };
  for (const line of state.lines) {
    routes[`PATCH /pantry/receipts/5/lines/${line.id}`] = async (req) => {
      const patch = (await req.json()) as ReceiptLinePatch;
      const l = state.lines.find((x) => x.id === line.id) as ReceiptLine;
      if (patch.food_id === BANANA.id) {
        Object.assign(l, { food: BANANA, quantity: 1, unit: "medium", grams: 118, approx: true });
        l.expires_on = "2026-10-14";
      }
      if (patch.quantity != null) Object.assign(l, { quantity: patch.quantity, unit: patch.unit });
      if (patch.approx != null) l.approx = patch.approx;
      if (patch.expires_on !== undefined) l.expires_on = patch.expires_on;
      if (patch.status) l.status = patch.status;
      else l.status = "edited";
      return Response.json(l);
    };
  }
  return routes;
}

function setup(routes: Routes = receiptServer(), giveUpAfterMs?: number) {
  const calls = mockApi(routes);
  renderWithClient(<ReceiptReview id={5} giveUpAfterMs={giveUpAfterMs} />);
  return calls;
}

const line = (name: RegExp | string) =>
  within(screen.getByRole("list", { name: "Receipt lines" })).getByRole("listitem", { name });

describe("helpers", () => {
  it("formats a line's amount and knows what gets added", () => {
    const [milk, tomatoes, unknown] = makeReceipt().lines;
    expect(lineAmount(milk)).toBe("2.27 l · 2340 g");
    expect(lineAmount(tomatoes)).toBe("400 g");
    expect(lineAmount(unknown)).toBe("");
    expect([milk, tomatoes, unknown].map(willAdd)).toEqual([true, true, false]);
    expect(willAdd({ ...milk, status: "rejected" })).toBe(false);
  });
});

describe("ReceiptReview: reading", () => {
  it("polls while the worker reads, then shows the lines", async () => {
    let gets = 0;
    const statuses = ["queued", "processing", "ready"] as const;
    const calls = setup({
      ...receiptServer(),
      "GET /pantry/receipts/5": () => {
        const status = statuses[Math.min(gets++, 2)];
        return Response.json(
          makeReceipt({ status, lines: status === "ready" ? makeReceipt().lines : [] }),
        );
      },
    });

    expect(await screen.findByRole("status")).toHaveTextContent("Reading your receipt…");
    expect(
      await screen.findByRole("list", { name: "Receipt lines" }, { timeout: 3000 }),
    ).toBeInTheDocument();
    const polls = calls.filter((c) => c.path === "/pantry/receipts/5").length;
    expect(polls).toBe(3);

    // Ready: polling has stopped.
    await new Promise((r) => setTimeout(r, 700));
    expect(calls.filter((c) => c.path === "/pantry/receipts/5")).toHaveLength(polls);
  });

  it("gives up after a while with a way to check again or delete", async () => {
    let gets = 0;
    setup(
      {
        ...receiptServer(),
        "GET /pantry/receipts/5": () => {
          gets += 1;
          return Response.json(makeReceipt({ status: "queued", lines: [] }));
        },
      },
      50,
    );

    expect(await screen.findByText("This is taking longer than it should")).toBeInTheDocument();
    const after = gets;
    await new Promise((r) => setTimeout(r, 700));
    expect(gets).toBe(after);

    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(gets).toBeGreaterThan(after));
    expect(screen.getByRole("button", { name: "Delete receipt" })).toBeInTheDocument();
  });

  it("shows why a receipt failed, with retry and delete", async () => {
    const calls = setup({
      ...receiptServer(),
      "GET /pantry/receipts/5": json(
        makeReceipt({
          status: "failed",
          source: "image",
          error: "Couldn't open the photo.",
          lines: [],
        }),
      ),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't open the photo.");
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute(
      "href",
      "/pantry/receipts",
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete receipt" }));
    await waitFor(() => expect(nav.push).toEqual(["/pantry/receipts"]));
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/pantry/receipts/5")).toBe(true);
  });
});

describe("ReceiptReview: review", () => {
  it("shows each line, marks the unmatched one and counts what will be added", async () => {
    setup();

    const milk = await screen.findByRole("listitem", { name: MILK.description });
    expect(milk).toHaveTextContent("SEMI SKMD MILK 4PT");
    expect(milk).toHaveTextContent("2.27 l · 2340 g");
    expect(milk).toHaveTextContent("use by Fri 16 Oct");
    expect(line(/No match — pick a food/)).toHaveTextContent("MYSTERY SNACK");
    expect(screen.getByText("2 items will be added")).toBeInTheDocument();
    expect(screen.getByText("1 line without a food will be skipped")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add 2 items to pantry" })).toBeEnabled();
  });

  it("rejects and restores a line", async () => {
    const calls = setup();

    fireEvent.click(await screen.findByRole("button", { name: `Reject ${MILK.description}` }));
    expect(await screen.findByText("1 item will be added")).toBeInTheDocument();
    expect(line(MILK.description)).toHaveTextContent("Won't be added");
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "rejected" });

    fireEvent.click(screen.getByRole("button", { name: `Restore ${MILK.description}` }));
    expect(await screen.findByText("2 items will be added")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body).toEqual({ status: "suggested" });
  });

  it("edits the amount and use-by date", async () => {
    const calls = setup();

    fireEvent.click(await screen.findByRole("button", { name: `Edit ${MILK.description}` }));
    const form = screen.getByRole("form", { name: `Edit ${MILK.description}` });
    fireEvent.change(within(form).getByLabelText("Quantity"), { target: { value: "1" } });
    fireEvent.change(within(form).getByLabelText("Use by"), { target: { value: "2026-10-12" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(line(MILK.description)).toHaveTextContent("use by Mon 12 Oct"));
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      quantity: 1,
      unit: "l",
      expires_on: "2026-10-12",
      approx: false,
    });
  });

  it("picks a food for an unmatched line, which then counts", async () => {
    const calls = setup();

    fireEvent.click(await screen.findByRole("button", { name: "Pick a food for mystery snack" }));
    fireEvent.change(screen.getByLabelText('Search foods for "mystery snack"'), {
      target: { value: "banana" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Bananas, raw/ }));

    expect(await screen.findByText("3 items will be added")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ food_id: BANANA.id });
    // The editor stays open on the server's estimate.
    const form = screen.getByRole("form", { name: `Edit ${BANANA.description}` });
    expect(within(form).getByLabelText("Quantity")).toHaveValue(1);
    expect(line(BANANA.description)).toHaveTextContent("approx");
  });

  it("confirms, toasts the count and goes back to the pantry", async () => {
    const calls = setup();

    fireEvent.click(await screen.findByRole("button", { name: `Reject ${MILK.description}` }));
    fireEvent.click(await screen.findByRole("button", { name: "Add 1 item to pantry" }));

    await waitFor(() => expect(nav.push).toEqual(["/pantry"]));
    expect(toast.success).toHaveBeenCalledWith("Added 1 item to your pantry");
    expect(calls.some((c) => c.method === "POST" && c.path === "/pantry/receipts/5/confirm")).toBe(
      true,
    );
  });

  it("can't confirm when nothing would be added", async () => {
    setup(
      receiptServer(
        makeReceipt({ lines: [receiptLine(3, { raw_text: "MYSTERY   £1.00", name: "mystery" })] }),
      ),
    );

    expect(await screen.findByText("0 items will be added")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add 0 items to pantry" })).toBeDisabled();
  });

  it("shows a confirmed receipt read-only", async () => {
    const receipt = makeReceipt({ status: "confirmed" });
    receipt.lines[0].pantry_item_id = 9;
    setup({ ...receiptServer(), "GET /pantry/receipts/5": json(receipt) });

    expect(
      await screen.findByText("1 item from this receipt is in your pantry."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reject/ })).not.toBeInTheDocument();
  });
});
