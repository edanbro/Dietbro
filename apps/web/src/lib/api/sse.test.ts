import { afterEach, describe, expect, it, vi } from "vitest";

import { bodyOf, frame } from "@/test/sse";

import { ApiError } from "./browser";
import {
  type ChatEvent,
  type ChatMessageIn,
  ChatProblemError,
  ChatStreamDropped,
  isChatProblem,
  readChatEvents,
  readSSE,
  sendChatMessage,
} from "./sse";

async function collect<T>(it: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const x of it) out.push(x);
  return out;
}

const data = async (chunks: (string | Uint8Array)[]) =>
  (await collect(readSSE(bodyOf(chunks)))).map((m) => m.data);

describe("readSSE", () => {
  it("reads several events from one chunk", async () => {
    expect(await data(["data: a\n\ndata: b\n\n"])).toEqual(["a", "b"]);
  });

  it("joins an event split across chunks, even mid-line", async () => {
    expect(await data(["da", "ta: hel", "lo\n", "\n"])).toEqual(["hello"]);
  });

  it("skips comments and keep-alive pings", async () => {
    expect(await data([": ping\n\n", "data: a\n", ": ping\n", "\n", ":\n\n"])).toEqual(["a"]);
  });

  it("accepts CRLF and CR line endings, including a CRLF split across chunks", async () => {
    expect(await data(["data: a\r\n\r\n", "data: b\r", "\n\r\n", "data: c\r\rdata: d\r", "\r"]))
      .toEqual(["a", "b", "c", "d"]);
  });

  it("joins multi-line data with newlines and strips one leading space", async () => {
    expect(await data(["data: line 1\ndata:line 2\ndata:  indented\ndata\n\n"])).toEqual([
      "line 1\nline 2\n indented\n",
    ]);
  });

  it("keeps the event name and id and ignores unknown fields", async () => {
    const messages = await collect(
      readSSE(bodyOf(["event: update\nid: 7\nretry: 100\nfoo: bar\ndata: x\n\ndata: y\n\n"])),
    );
    expect(messages).toEqual([
      { event: "update", data: "x", id: "7" },
      { event: "message", data: "y", id: "7" },
    ]);
  });

  it("drops an event the stream cut off and blank events", async () => {
    expect(await data(["\n\ndata: a\n\nevent: x\n\ndata: b"])).toEqual(["a"]);
  });

  it("decodes multi-byte characters split across chunks", async () => {
    const bytes = new TextEncoder().encode("data: crème brûlée 🍮\n\n");
    expect(await data([bytes.slice(0, 9), bytes.slice(9, 23), bytes.slice(23)])).toEqual([
      "crème brûlée 🍮",
    ]);
  });
});

describe("readChatEvents", () => {
  it("yields typed events and skips unknown types", async () => {
    const events = await collect(
      readChatEvents(
        bodyOf([
          frame({ type: "status", text: "Looking for spicy dinners…" }),
          'data: {"type":"future_thing"}\n\n',
          frame({ type: "text", delta: "Done." }),
        ]),
      ),
    );
    expect(events).toEqual([
      { type: "status", text: "Looking for spicy dinners…" },
      { type: "text", delta: "Done." },
    ]);
  });

  it("treats unreadable data as a dropped stream", async () => {
    await expect(collect(readChatEvents(bodyOf(["data: {nope\n\n"])))).rejects.toBeInstanceOf(
      ChatStreamDropped,
    );
  });
});

describe("isChatProblem", () => {
  it("recognises the gate's answers only", () => {
    expect(isChatProblem({ code: "busy", detail: ["Still answering"] })).toBe(true);
    expect(isChatProblem({ code: "nope", detail: [] })).toBe(false);
    expect(isChatProblem({ detail: "Not Found" })).toBe(false);
    expect(isChatProblem(null)).toBe(false);
  });
});

describe("sendChatMessage", () => {
  const body: ChatMessageIn = {
    text: "skip dinner tonight",
    client_id: "5f0c6f5e-3c8a-4c55-9a39-2f1f3c1b7a10",
    today: "2026-10-09",
    local_time: "18:30:00",
  };
  const thread: ChatEvent = {
    type: "thread",
    thread_id: 3,
    message_id: 11,
    mode: "offline",
    offline_reason: "no_key",
  };

  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(answer: (req: Request) => Response | Promise<Response>) {
    const requests: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (req: Request) => {
        requests.push(req);
        return answer(req);
      }),
    );
    return requests;
  }

  it("posts with the bearer token and relays events up to done", async () => {
    const done: ChatEvent = {
      type: "done",
      messages_today: 4,
      message: {
        id: 12,
        role: "assistant",
        text: "Skipped tonight's dinner.",
        created_at: "2026-10-09T17:30:00Z",
        plan_id: 8,
        mode: "offline",
        offline_reason: "no_key",
        attachments: [],
        suggestions: [],
      },
    };
    const requests = stubFetch(
      () =>
        new Response(
          bodyOf([frame(thread), ": ping\n\n", frame({ type: "text", delta: "Skipped" }), frame(done)]),
          { headers: { "Content-Type": "text/event-stream" } },
        ),
    );
    const seen: ChatEvent[] = [];

    const last = await sendChatMessage("https://api.test", "tok", body, (e) => seen.push(e));

    expect(last).toEqual(done);
    expect(seen.map((e) => e.type)).toEqual(["thread", "text", "done"]);
    const req = requests[0];
    expect(req.method).toBe("POST");
    expect(req.url).toBe("https://api.test/chat/messages");
    expect(req.headers.get("Authorization")).toBe("Bearer tok");
    expect(req.headers.get("Accept")).toBe("text/event-stream");
    expect(await req.json()).toEqual(body);
  });

  it("sends no Authorization header without a token", async () => {
    const requests = stubFetch(
      () => new Response(bodyOf([frame({ type: "error", message: "Something went wrong" })])),
    );
    const last = await sendChatMessage("https://api.test", null, body, () => undefined);
    expect(last).toEqual({ type: "error", message: "Something went wrong" });
    expect(requests[0].headers.has("Authorization")).toBe(false);
  });

  it("maps the gate's JSON refusals to ChatProblemError", async () => {
    stubFetch(() =>
      Response.json(
        { code: "daily_limit", detail: ["60 messages a day"], retry_at: "2026-10-10T09:00:00Z" },
        { status: 429 },
      ),
    );
    const error = await sendChatMessage("https://api.test", "t", body, () => undefined).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(ChatProblemError);
    const problem = error as ChatProblemError;
    expect(problem.status).toBe(429);
    expect(problem.code).toBe("daily_limit");
    expect(problem.problem.retry_at).toBe("2026-10-10T09:00:00Z");
    expect(problem.messages).toEqual(["60 messages a day"]);
  });

  it("maps other errors to ApiError", async () => {
    stubFetch(() => Response.json({ detail: "Invalid token" }, { status: 401 }));
    const error = await sendChatMessage("https://api.test", "t", body, () => undefined).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(ChatProblemError);
    expect((error as ApiError).messages).toEqual(["Invalid token"]);
  });

  it("reports a stream that closes before done as dropped", async () => {
    stubFetch(() => new Response(bodyOf([frame(thread)])));
    const seen: ChatEvent[] = [];
    await expect(
      sendChatMessage("https://api.test", "t", body, (e) => seen.push(e)),
    ).rejects.toBeInstanceOf(ChatStreamDropped);
    expect(seen).toEqual([thread]);
  });

  it("reports a broken connection as dropped", async () => {
    stubFetch(
      () =>
        new Response(
          new ReadableStream<Uint8Array>({
            start(c) {
              c.enqueue(new TextEncoder().encode(frame(thread)));
              c.error(new TypeError("network error"));
            },
          }),
        ),
    );
    await expect(
      sendChatMessage("https://api.test", "t", body, () => undefined),
    ).rejects.toBeInstanceOf(ChatStreamDropped);
  });

  it("reports an unreachable server as dropped", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    await expect(
      sendChatMessage("https://api.test", "t", body, () => undefined),
    ).rejects.toBeInstanceOf(ChatStreamDropped);
  });

  it("passes an abort through unchanged", async () => {
    const controller = new AbortController();
    stubFetch(() => {
      controller.abort();
      return Promise.reject(new DOMException("aborted", "AbortError"));
    });
    const error = await sendChatMessage(
      "https://api.test",
      "t",
      body,
      () => undefined,
      controller.signal,
    ).catch((e: unknown) => e);
    expect(error).not.toBeInstanceOf(ChatStreamDropped);
    expect((error as DOMException).name).toBe("AbortError");
  });
});
