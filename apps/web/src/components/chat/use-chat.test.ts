import { describe, expect, it } from "vitest";

import { chatMessage, makeOutcome, makeThread } from "@/test/fixtures";

import { applyEvent, settled, startTurn } from "./use-chat";

describe("applyEvent", () => {
  it("folds a stream into the live turn", () => {
    let turn = startTurn("skip dinner tonight", "id-1");
    expect(turn.phase).toBe("sending");

    turn = applyEvent(turn, {
      type: "thread",
      thread_id: 3,
      message_id: 11,
      mode: "llm",
      offline_reason: null,
    });
    turn = applyEvent(turn, { type: "status", text: "Checking your plan…" });
    expect(turn).toMatchObject({ phase: "streaming", threadId: 3, userMessageId: 11 });
    expect(turn.status).toBe("Checking your plan…");

    turn = applyEvent(turn, { type: "text", delta: "Sure" });
    turn = applyEvent(turn, { type: "text_reset" });
    turn = applyEvent(turn, { type: "text", delta: "Done." });
    turn = applyEvent(turn, makeOutcome());
    turn = applyEvent(turn, { type: "recipe", recipe_id: 4, name: "Dal" });
    expect(turn.status).toBeNull();
    expect(turn.streamed).toBe("Done.");
    expect(turn.attachments.map((a) => a.type)).toEqual(["outcome", "recipe"]);
  });
});

describe("settled", () => {
  const turn = { threadId: 3, userMessageId: 11 };
  const mine = chatMessage(11, "user", "skip dinner tonight");

  it("waits while the reply is pending or the message isn't stored yet", () => {
    expect(settled(undefined, turn)).toBe(false);
    expect(settled(makeThread(), turn)).toBe(false);
    expect(
      settled(
        makeThread({ messages: [mine], pending: { message_id: 11, started_at: "" } }),
        turn,
      ),
    ).toBe(false);
    expect(settled(makeThread({ messages: [mine] }), { ...turn, userMessageId: null })).toBe(false);
  });

  it("is done once the message is stored and nothing is pending, or the thread moved on", () => {
    expect(settled(makeThread({ messages: [mine] }), turn)).toBe(true);
    expect(settled(makeThread({ thread_id: 4 }), turn)).toBe(true);
  });
});
