/**
 * The chat's streamed replies. POST /chat/messages answers with server-sent events, but
 * `EventSource` can only GET and can't send the Authorization header, so the body of a plain
 * `fetch` is read here instead (ADR-0013).
 */
import { ApiError, errorMessages } from "./browser";
import type { components } from "./schema";

type S = components["schemas"];

export type ChatMessageIn = S["ChatMessageIn"];
export type ChatProblem = S["ChatProblem"];
export type DoneEvent = S["DoneEvent"];
export type ErrorEvent = S["ErrorEvent"];
/** One `data:` payload of the stream: thread, then status / text / text_reset / outcome /
 * recipe, then done or error. */
export type ChatEvent =
  | S["ThreadEvent"]
  | S["StatusEvent"]
  | S["TextEvent"]
  | S["TextResetEvent"]
  | S["OutcomeEvent"]
  | S["RecipeEvent"]
  | DoneEvent
  | ErrorEvent;

export type SSEMessage = { event: string; data: string; id: string };

/**
 * Parse a `text/event-stream` body as the WHATWG spec does: lines end in CRLF, LF or CR (a CR
 * at the end of a chunk waits for the next one, in case it is half of a CRLF); `:` lines are
 * comments (keep-alive pings); `data:` lines join with "\n"; a blank line dispatches; an event
 * cut off by the end of the stream is dropped. Events may be split across chunks, and one chunk
 * may hold several (multi-byte characters split across chunks are decoded whole).
 */
export async function* readSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const lineEnd = /\r\n|\r|\n/g; // per stream: a shared /g regex would mix up lastIndex
  let buffer = "";
  let data: string[] = [];
  let event = "";
  let id = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let start = 0;
      lineEnd.lastIndex = 0;
      for (let m = lineEnd.exec(buffer); m; m = lineEnd.exec(buffer)) {
        if (!done && m[0] === "\r" && m.index === buffer.length - 1) break;
        const line = buffer.slice(start, m.index);
        start = lineEnd.lastIndex;
        if (line === "") {
          if (data.length) yield { event: event || "message", data: data.join("\n"), id };
          data = [];
          event = "";
          continue;
        }
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        let value = colon < 0 ? "" : line.slice(colon + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (field === "data") data.push(value);
        else if (field === "event") event = value;
        else if (field === "id" && !value.includes("\0")) id = value;
      }
      buffer = buffer.slice(start);
      if (done) return;
    }
  } finally {
    // Leaving early (after `done`, or on an error) must not leave the connection open.
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

const EVENT_TYPES = new Set<string>([
  "thread",
  "status",
  "text",
  "text_reset",
  "outcome",
  "recipe",
  "done",
  "error",
]);

/** The stream ended (network error, unreadable data, or closed early) before `done`/`error`.
 * The turn runs on regardless (the server detaches it), so the client reloads the thread. */
export class ChatStreamDropped extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "ChatStreamDropped";
  }
}

/** A gate refusal (400/404/409/429) with its machine-readable code. */
export class ChatProblemError extends ApiError {
  constructor(
    status: number,
    readonly problem: ChatProblem,
  ) {
    super(status, problem.detail);
    this.name = "ChatProblemError";
  }

  get code(): ChatProblem["code"] {
    return this.problem.code;
  }
}

/** Typed chat events from an SSE body. Unknown event types are skipped (newer servers). */
export async function* readChatEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<ChatEvent> {
  for await (const message of readSSE(body)) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(message.data);
    } catch (cause) {
      throw new ChatStreamDropped("unreadable event in the reply stream", { cause });
    }
    const type = (parsed as { type?: unknown } | null)?.type;
    if (typeof type === "string" && EVENT_TYPES.has(type)) yield parsed as ChatEvent;
  }
}

const PROBLEM_CODES = new Set<string>([
  "bad_today",
  "thread_not_found",
  "busy",
  "duplicate",
  "daily_limit",
]);

export function isChatProblem(body: unknown): body is ChatProblem {
  const b = body as Partial<ChatProblem> | null | undefined;
  return typeof b?.code === "string" && PROBLEM_CODES.has(b.code) && Array.isArray(b.detail);
}

async function responseError(response: Response): Promise<ApiError> {
  const body: unknown = await response.json().catch(() => undefined);
  if (isChatProblem(body)) return new ChatProblemError(response.status, body);
  return new ApiError(response.status, errorMessages(body));
}

/**
 * Send a chat message and relay its streamed reply to `onEvent`, in order.
 *
 * Resolves with the closing `done` or `error` event. Throws ChatProblemError for the gate's
 * refusals, ApiError for other non-2xx answers, ChatStreamDropped when the server can't be
 * reached or the stream breaks before it closes (resending is safe: same `client_id`), and the
 * abort error when `signal` aborts.
 */
export async function sendChatMessage(
  baseUrl: string,
  token: string | null,
  body: ChatMessageIn,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<DoneEvent | ErrorEvent> {
  const headers = new Headers({
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const request = new Request(`${baseUrl}/chat/messages`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });

  let response: Response;
  try {
    response = await fetch(request);
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ChatStreamDropped("couldn't reach the server", { cause });
  }
  if (!response.ok) throw await responseError(response);
  if (!response.body) throw new ChatStreamDropped("the reply had no body");

  try {
    for await (const event of readChatEvents(response.body)) {
      onEvent(event);
      if (event.type === "done" || event.type === "error") return event;
    }
  } catch (cause) {
    if (signal?.aborted) throw cause;
    if (cause instanceof ChatStreamDropped) throw cause;
    throw new ChatStreamDropped("the reply stream was interrupted", { cause });
  }
  throw new ChatStreamDropped("the reply stream ended early");
}
