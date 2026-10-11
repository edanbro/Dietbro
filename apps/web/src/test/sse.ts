/** A server-sent-events response whose chunks the test pushes one at a time. */
import type { ChatEvent } from "@/lib/api/sse";

export function frame(event: ChatEvent): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

/** A body that yields `chunks` (strings or bytes) and closes. */
export function bodyOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(typeof c === "string" ? encoder.encode(c) : c);
      controller.close();
    },
  });
}

export function sseStream() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: () =>
      new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    send(...events: ChatEvent[]) {
      controller.enqueue(encoder.encode(events.map(frame).join("")));
    },
    raw(text: string) {
      controller.enqueue(encoder.encode(text));
    },
    close() {
      controller.close();
    },
    /** The connection drops (a phone locked, a tunnel). */
    fail() {
      controller.error(new TypeError("network error"));
    },
  };
}
