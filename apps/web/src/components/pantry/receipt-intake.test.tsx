import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { localISODate } from "@/lib/dates";
import { json, mockApi, renderWithClient, type Routes } from "@/test/api";
import { makeReceipt } from "@/test/fixtures";
import { calls as nav, resetNavigation } from "@/test/navigation";

import { MAX_PHOTO_BYTES, photoProblem, ReceiptIntake } from "./receipt-intake";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));

beforeEach(() => resetNavigation("/pantry/receipts"));
afterEach(() => vi.unstubAllGlobals());

function setup(routes: Routes = {}) {
  const calls = mockApi({ "GET /pantry/receipts": json([]), ...routes });
  renderWithClient(<ReceiptIntake />);
  return calls;
}

const photo = (name: string, type: string, size = 1000) => ({ name, type, size });

describe("photoProblem", () => {
  it("accepts JPEG, PNG and WebP up to 8 MB", () => {
    expect(photoProblem(photo("r.jpg", "image/jpeg"))).toBeNull();
    expect(photoProblem(photo("r.png", "image/png"))).toBeNull();
    expect(photoProblem(photo("r.webp", "image/webp"))).toBeNull();
    expect(photoProblem(photo("r.jpeg", ""))).toBeNull();
  });

  it("explains HEIC, other types and big files", () => {
    expect(photoProblem(photo("IMG_1.HEIC", "image/heic"))).toMatch(/Most Compatible/);
    expect(photoProblem(photo("IMG_1.heic", ""))).toMatch(/HEIC/);
    expect(photoProblem(photo("r.pdf", "application/pdf"))).toMatch(/JPEG, PNG or WebP/);
    expect(photoProblem(photo("r.jpg", "image/jpeg", MAX_PHOTO_BYTES + 1))).toMatch(/8 MB/);
  });
});

describe("ReceiptIntake", () => {
  it("sends pasted text with today's local date and opens the receipt", async () => {
    const calls = setup({
      "POST /pantry/receipts/text": json(makeReceipt({ id: 9, status: "queued", lines: [] }), 202),
    });

    fireEvent.click(screen.getByRole("tab", { name: "Paste text" }));
    fireEvent.change(await screen.findByLabelText("Receipt text"), {
      target: { value: "MILK 4PT 1.45" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Read receipt" }));

    await waitFor(() => expect(nav.push).toEqual(["/pantry/receipts/9"]));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      text: "MILK 4PT 1.45",
      purchased_on: localISODate(),
    });
  });

  it("shows a failed upload's error and lets you try again", async () => {
    let posts = 0;
    setup({
      "POST /pantry/receipts/text": () => {
        posts += 1;
        return posts === 1
          ? Response.json(
              { detail: "You can add 20 receipts a day; try again tomorrow." },
              { status: 429 },
            )
          : Response.json(makeReceipt({ id: 9, status: "queued" }), { status: 202 });
      },
    });

    fireEvent.click(screen.getByRole("tab", { name: "Paste text" }));
    fireEvent.change(await screen.findByLabelText("Receipt text"), {
      target: { value: "MILK 1.45" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Read receipt" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("20 receipts a day");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(nav.push).toEqual(["/pantry/receipts/9"]));
  });

  it("refuses a HEIC photo before uploading", async () => {
    const calls = setup();

    const file = new File(["x"], "IMG_0001.HEIC", { type: "image/heic" });
    fireEvent.change(screen.getByLabelText("Choose a photo of the receipt"), {
      target: { files: [file] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("HEIC photos aren't supported");
    expect(screen.getByRole("button", { name: "Read receipt" })).toBeDisabled();
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);
  });

  it("uploads a photo as multipart form data", async () => {
    const calls = setup({
      "POST /pantry/receipts/image": json(
        makeReceipt({ id: 9, source: "image", status: "queued" }),
        202,
      ),
    });

    const file = new File(["\xff\xd8\xff"], "receipt.jpg", { type: "image/jpeg" });
    const input = screen.getByLabelText("Take a photo of the receipt");
    expect(input).toHaveAttribute("capture", "environment");
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Read receipt" }));

    await waitFor(() => expect(nav.push).toEqual(["/pantry/receipts/9"]));
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/pantry/receipts/image");
    // (jsdom's File loses its name crossing into Node's FormData; browsers keep it.)
    expect(String(post?.body)).toMatch(/name="file"; filename=.*\r\nContent-Type: image\/jpeg/);
    expect(String(post?.body)).toContain('name="purchased_on"');
  });

  it("lists recent receipts with their status", async () => {
    setup({
      "GET /pantry/receipts": json([
        {
          id: 9,
          source: "image",
          status: "ready",
          purchased_on: "2026-10-09",
          error: null,
          created_at: "2026-10-09T10:00:00Z",
          lines: 6,
        },
        {
          id: 8,
          source: "text",
          status: "failed",
          purchased_on: "2026-10-08",
          error: "No text found",
          created_at: "2026-10-08T10:00:00Z",
          lines: 0,
        },
      ]),
    });

    const ready = await screen.findByRole("link", { name: /Photo · Fri 9 Oct/ });
    expect(ready).toHaveAttribute("href", "/pantry/receipts/9");
    expect(ready).toHaveTextContent("Ready to review");
    expect(screen.getByRole("link", { name: /Pasted text/ })).toHaveTextContent("No text found");
  });
});
