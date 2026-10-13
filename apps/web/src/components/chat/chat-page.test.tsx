import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type ChatThread, keys } from "@/lib/api/hooks";
import type { ChatEvent } from "@/lib/api/sse";
import { json, mockApi, renderWithClient, type Routes } from "@/test/api";
import { chatMessage, makeOutcome, makePlan, makeThread } from "@/test/fixtures";
import * as navigation from "@/test/navigation";
import { resetNavigation } from "@/test/navigation";
import { sseStream } from "@/test/sse";

import { ChatPage } from "./chat-page";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const THREAD: ChatEvent = {
  type: "thread",
  thread_id: 3,
  message_id: 11,
  mode: "offline",
  offline_reason: "no_key",
};
const OUTCOME = makeOutcome();

function fakeTime(...fake: ("setInterval" | "clearInterval")[]) {
  vi.useFakeTimers({ toFake: ["Date", ...fake] });
  vi.setSystemTime(new Date(2026, 9, 9, 18, 30, 5)); // Friday evening
}

function setup(routes: Routes) {
  const calls = mockApi({ "GET /chat/thread": json(makeThread()), ...routes });
  const view = renderWithClient(<ChatPage />);
  return { calls, ...view };
}

/** GET /chat/thread answers these in turn, repeating the last. */
function threads(...pages: ChatThread[]) {
  let n = 0;
  return () => Response.json(pages[Math.min(n++, pages.length - 1)]);
}

const posts = (calls: { method: string; path: string; body: unknown }[]) =>
  calls.filter((c) => c.method === "POST" && c.path === "/chat/messages");
const threadGets = (calls: { method: string; path: string }[]) =>
  calls.filter((c) => c.method === "GET" && c.path === "/chat/thread").length;

async function type(text: string) {
  const box = await screen.findByRole("textbox", { name: "Message" });
  fireEvent.change(box, { target: { value: text } });
  return box;
}

async function send(text: string) {
  const box = await type(text);
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  return box;
}

beforeEach(() => fakeTime());

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ChatPage", () => {
  it("offers the example prompts when there is no conversation yet", async () => {
    const { calls } = setup({});

    fireEvent.click(await screen.findByRole("button", { name: "craving something spicy on Friday" }));

    const box = screen.getByRole("textbox", { name: "Message" });
    expect(box).toHaveValue("craving something spicy on Friday");
    expect(box).toHaveFocus();
    expect(screen.getByRole("list", { name: "Try:" })).toHaveTextContent("swap Thursday's dinner");
    expect(posts(calls)).toEqual([]);
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New chat" })).not.toBeInTheDocument();
  });

  it("streams a reply: optimistic bubble, status, text, cards, then the stored message", async () => {
    const stream = sseStream();
    const { calls, client } = setup({ "POST /chat/messages": () => stream.response() });
    client.setQueryData(keys.currentPlan, makePlan());

    const box = await send("skip dinner tonight");

    const log = await screen.findByRole("log", { name: "Conversation" });
    expect(within(log).getByText("skip dinner tonight")).toBeInTheDocument();
    expect(within(log).getByRole("status")).toHaveTextContent("Thinking…");
    expect(box).toHaveValue("");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toEqual({
      text: "skip dinner tonight",
      client_id: expect.stringMatching(UUID),
      thread_id: 3,
      today: "2026-10-09",
      local_time: "18:30:05",
    });

    // Typing goes on; sending waits for the reply.
    await type("and had pizza for lunch");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    stream.send(THREAD, { type: "status", text: "Updating your plan…" });
    expect(await within(log).findByText("Updating your plan…")).toBeInTheDocument();
    // The turn says replies are simple (no model key): the banner appears at once.
    expect(screen.getByRole("note")).toHaveTextContent("Simple replies: no AI key");

    stream.send({ type: "text", delta: "Done – skipping " }, { type: "text", delta: "dinner." });
    expect(await within(log).findByText("Done – skipping dinner.")).toBeInTheDocument();
    expect(within(log).queryByRole("status")).not.toBeInTheDocument();

    stream.send(OUTCOME, { type: "recipe", recipe_id: 4021, name: "Smoky bean chilli" });
    const card = await within(log).findByRole("article", { name: "Plan updated" });
    expect(card).toHaveTextContent("Today's dinner: Dinner 1 → no meal");
    expect(within(card).getByRole("link", { name: "See plan" })).toHaveAttribute(
      "href",
      "/plan?day=2026-10-09",
    );
    expect(within(log).getByRole("link", { name: /Smoky bean chilli/ })).toHaveAttribute(
      "href",
      "/recipes/4021",
    );
    // The new plan version is saved before the outcome is sent: /plan must refetch.
    expect(client.getQueryState(keys.currentPlan)?.isInvalidated).toBe(true);

    stream.send({
      type: "done",
      messages_today: 5,
      message: chatMessage(12, "assistant", "Skipped tonight's dinner. Enjoy your evening!", {
        plan_id: 8,
        attachments: [OUTCOME, { type: "recipe", recipe_id: 4021, name: "Smoky bean chilli" }],
        suggestions: ["undo that"],
      }),
    });

    expect(
      await within(log).findByText("Skipped tonight's dinner. Enjoy your evening!"),
    ).toBeInTheDocument();
    expect(within(log).queryByText("Done – skipping dinner.")).not.toBeInTheDocument();
    expect(within(log).getAllByRole("article", { name: "Plan updated" })).toHaveLength(1);
    expect(within(log).getByText("skip dinner tonight")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "undo that" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(client.getQueryData<ChatThread>(keys.chatThread)?.messages.map((m) => m.id)).toEqual([
      11, 12,
    ]);
  });

  it("drops the streamed text on text_reset", async () => {
    const stream = sseStream();
    setup({ "POST /chat/messages": () => stream.response() });

    await send("craving satay tonight");
    stream.send(THREAD, { type: "text", delta: "Sure, satay it" });
    const log = await screen.findByRole("log");
    expect(await within(log).findByText("Sure, satay it")).toBeInTheDocument();

    stream.send({ type: "text_reset" });

    await waitFor(() => expect(within(log).queryByText("Sure, satay it")).not.toBeInTheDocument());
    expect(within(log).getByRole("status")).toHaveTextContent("Thinking…");

    stream.send({ type: "text", delta: "Satay has peanuts, so I can't plan it." });
    expect(
      await within(log).findByText("Satay has peanuts, so I can't plan it."),
    ).toBeInTheDocument();
  });

  it("sends a suggestion chip when tapped", async () => {
    const stream = sseStream();
    const { calls } = setup({
      "GET /chat/thread": json(
        makeThread({
          messages: [
            chatMessage(1, "user", "skip lunch on Friday"),
            chatMessage(2, "assistant", "Which meal did you mean?", {
              suggestions: ["skip Friday lunch", "skip Friday dinner"],
            }),
          ],
        }),
      ),
      "POST /chat/messages": () => stream.response(),
    });

    const chips = await screen.findByRole("list", { name: "Suggested replies" });
    fireEvent.click(within(chips).getByRole("button", { name: "skip Friday dinner" }));

    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toMatchObject({ text: "skip Friday dinner" });
    expect(screen.queryByRole("list", { name: "Suggested replies" })).not.toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveTextContent("skip Friday dinner");
  });

  it("disables the composer at the daily limit and says when it reopens", async () => {
    const { calls } = setup({
      "POST /chat/messages": json(
        {
          code: "daily_limit",
          detail: ["You've sent 60 messages in the last 24 hours."],
          retry_at: new Date(2026, 9, 9, 21, 15).toISOString(),
        },
        429,
      ),
    });

    const box = await send("had pizza for lunch");

    expect(await screen.findByText(/You can send again at 21:15\./)).toBeInTheDocument();
    expect(box).toBeDisabled();
    expect(box).toHaveValue("had pizza for lunch");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.queryByRole("log")).not.toBeInTheDocument();
    expect(posts(calls)).toHaveLength(1);
  });

  it("shows the limit from the thread's own count", async () => {
    setup({
      "GET /chat/thread": json(
        makeThread({
          messages: [chatMessage(1, "user", "hi"), chatMessage(2, "assistant", "Hello!")],
          messages_today: 60,
        }),
      ),
    });

    expect(await screen.findByText(/today's limit of 60 messages/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();
  });

  it("reloads the thread when the server is still busy with another message", async () => {
    const pending = makeThread({
      messages: [chatMessage(9, "user", "skip lunch")],
      pending: { message_id: 9, started_at: "2026-10-09T17:29:00Z" },
    });
    const { calls } = setup({
      "GET /chat/thread": threads(makeThread(), pending),
      "POST /chat/messages": json(
        { code: "busy", detail: ["Still answering message 9"], message_id: 9 },
        409,
      ),
    });

    const box = await send("had pizza for lunch");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Still answering your last message. Send this once it's done.",
    );
    expect(await screen.findByText("Still working on your last message…")).toBeInTheDocument();
    expect(box).toHaveValue("had pizza for lunch");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(threadGets(calls)).toBe(2);
  });

  it("reloads the thread for a message that was already answered", async () => {
    const answered = makeThread({
      messages: [
        chatMessage(11, "user", "skip dinner tonight"),
        chatMessage(12, "assistant", "Skipped tonight's dinner."),
      ],
    });
    setup({
      "GET /chat/thread": threads(makeThread(), answered),
      "POST /chat/messages": json({ code: "duplicate", detail: ["Already answered"] }, 409),
    });

    const box = await send("skip dinner tonight");

    expect(await screen.findByText("Skipped tonight's dinner.")).toBeInTheDocument();
    expect(box).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [{ offline_reason: "no_key" as const }, "Simple replies: no AI key"],
    [
      { offline_reason: "budget" as const, llm_resets_at: new Date(2026, 9, 10, 1, 0).toISOString() },
      "AI replies paused until tomorrow at 01:00",
    ],
    [{ offline_reason: "model_error" as const }, "Simple replies: the AI isn't responding"],
  ])("explains offline replies (%o)", async (thread, title) => {
    setup({ "GET /chat/thread": json(makeThread({ llm_available: false, ...thread })) });

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(title);
    expect(note).toHaveTextContent("skip dinner tonight");
  });

  it("starts a new chat", async () => {
    const { calls } = setup({
      "GET /chat/thread": json(
        makeThread({
          messages: [chatMessage(1, "user", "hi"), chatMessage(2, "assistant", "Hello!")],
        }),
      ),
      "POST /chat/threads": json(makeThread({ thread_id: 4 }), 201),
    });

    fireEvent.click(await screen.findByRole("button", { name: "New chat" }));

    expect(await screen.findByText("Tell Mealwright what changed")).toBeInTheDocument();
    expect(screen.queryByText("Hello!")).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/chat/threads")).toBe(true);
  });

  it("loads earlier messages on request", async () => {
    setup({
      "GET /chat/thread": (req) =>
        new URL(req.url).searchParams.get("before_id") === "5"
          ? Response.json(makeThread({ messages: [chatMessage(4, "user", "older one")] }))
          : Response.json(
              makeThread({ messages: [chatMessage(5, "assistant", "newer one")], has_more: true }),
            ),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Show earlier messages" }));

    expect(await screen.findByText("older one")).toBeInTheDocument();
    const log = screen.getByRole("log");
    expect(log.textContent?.indexOf("older one")).toBeLessThan(
      log.textContent?.indexOf("newer one") ?? -1,
    );
    expect(screen.queryByRole("button", { name: "Show earlier messages" })).not.toBeInTheDocument();
  });

  it("offers a retry with the same id when the server can't be reached", async () => {
    const stream = sseStream();
    let n = 0;
    const { calls } = setup({
      "POST /chat/messages": () =>
        n++ === 0 ? Promise.reject(new TypeError("Failed to fetch")) : stream.response(),
    });

    await send("skip dinner tonight");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't reach Mealwright.");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled(); // nothing typed

    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(posts(calls)).toHaveLength(2));
    const [first, second] = posts(calls).map((c) => c.body as { client_id: string });
    expect(second.client_id).toBe(first.client_id);
    expect(await screen.findByText("Thinking…")).toBeInTheDocument();
  });

  it("shows the stored reply after an error event", async () => {
    const stream = sseStream();
    setup({
      "GET /chat/thread": threads(
        makeThread(),
        makeThread({
          messages: [
            chatMessage(11, "user", "skip dinner tonight"),
            chatMessage(12, "assistant", "Something went wrong; your plan wasn't changed."),
          ],
        }),
      ),
      "POST /chat/messages": () => stream.response(),
    });

    await send("skip dinner tonight");
    stream.send(THREAD, { type: "error", message: "The assistant hit a problem." });

    expect(
      await screen.findByText("Something went wrong; your plan wasn't changed."),
    ).toBeInTheDocument();
    expect(screen.queryByText("The assistant hit a problem.")).not.toBeInTheDocument();
    expect(screen.getAllByText("skip dinner tonight")).toHaveLength(1);
  });
});

describe("waiting for a reply saved elsewhere", () => {
  const user = chatMessage(11, "user", "skip dinner tonight");
  const pending = makeThread({
    messages: [user],
    pending: { message_id: 11, started_at: "2026-10-09T17:30:00Z" },
  });
  const answered = makeThread({
    messages: [user, chatMessage(12, "assistant", "Skipped tonight's dinner.", { plan_id: 8 })],
    messages_today: 1,
  });

  async function tick() {
    await act(() => vi.advanceTimersByTimeAsync(2_000));
  }

  it("polls every 2 s while a reply is pending, then stops", async () => {
    fakeTime("setInterval", "clearInterval");
    const { calls } = setup({ "GET /chat/thread": threads(pending, pending, answered) });

    expect(await screen.findByText("Still working on your last message…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New chat" })).toBeDisabled();
    await type("thanks");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    await tick();
    await waitFor(() => expect(threadGets(calls)).toBe(2));
    expect(screen.getByText("Still working on your last message…")).toBeInTheDocument();

    await tick();
    expect(await screen.findByText("Skipped tonight's dinner.")).toBeInTheDocument();
    expect(screen.queryByText("Still working on your last message…")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();

    await tick();
    await tick();
    expect(threadGets(calls)).toBe(3);
  });

  it("checks again when the page becomes visible", async () => {
    fakeTime("setInterval", "clearInterval");
    const before = makeThread({ messages: [chatMessage(1, "user", "hi")] });
    const { calls } = setup({ "GET /chat/thread": threads(before, pending, answered) });

    expect(await screen.findByText("hi")).toBeInTheDocument();
    await tick();
    expect(threadGets(calls)).toBe(1); // nothing pending: no polling

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(await screen.findByText("Still working on your last message…")).toBeInTheDocument();
    await tick();
    expect(await screen.findByText("Skipped tonight's dinner.")).toBeInTheDocument();
  });

  it("polls for the reply when the stream drops, and refreshes the plan", async () => {
    fakeTime("setInterval", "clearInterval");
    const stream = sseStream();
    const { calls, client } = setup({
      "GET /chat/thread": threads(makeThread(), pending, answered),
      "POST /chat/messages": () => stream.response(),
    });
    client.setQueryData(keys.currentPlan, makePlan());

    await send("skip dinner tonight");
    stream.send(THREAD, { type: "text", delta: "Skipping" });
    expect(await screen.findByText("Skipping")).toBeInTheDocument();

    stream.fail();

    expect(
      await screen.findByText("Connection lost. Waiting for the reply…"),
    ).toBeInTheDocument();
    await waitFor(() => expect(threadGets(calls)).toBe(2));
    expect(screen.getAllByText("skip dinner tonight")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    await tick();

    expect(await screen.findByText("Skipped tonight's dinner.")).toBeInTheDocument();
    expect(screen.queryByText("Connection lost. Waiting for the reply…")).not.toBeInTheDocument();
    expect(screen.queryByText("Skipping")).not.toBeInTheDocument();
    expect(screen.getAllByText("skip dinner tonight")).toHaveLength(1);
    // The reply made plan 8; the cached plan (7) is stale now.
    expect(client.getQueryState(keys.currentPlan)?.isInvalidated).toBe(true);
    await tick();
    expect(threadGets(calls)).toBe(3);
  });
});

describe("errors", () => {
  it("explains a thread that can't be loaded", async () => {
    setup({ "GET /chat/thread": json({ detail: "Not signed in" }, 401) });
    expect(await screen.findByRole("alert")).toHaveTextContent("Not signed in");
  });

  it("restores the message and says why when the API refuses it", async () => {
    setup({
      "POST /chat/messages": json(
        { detail: [{ loc: ["body", "text"], msg: "String should have at most 1000 characters" }] },
        422,
      ),
    });

    const box = await send("x");

    expect(await screen.findByRole("alert")).toHaveTextContent("text: String should have");
    expect(box).toHaveValue("x");
  });
});

describe("ChatPage prompt links", () => {
  it("fills the composer from ?prompt= and drops it from the URL", async () => {
    resetNavigation("/chat?prompt=What%20can%20I%20make%20with%20spinach%3F");
    mockApi({ "GET /chat/thread": json(makeThread()) });
    renderWithClient(<ChatPage />);

    expect(await screen.findByDisplayValue("What can I make with spinach?")).toBeInTheDocument();
    expect(navigation.calls.replace).toContain("/chat");
  });
});
