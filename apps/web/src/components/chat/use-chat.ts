"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/browser";
import {
  mergeMessages,
  useChatSender,
  useChatThread,
  useEarlierMessages,
  useNewChatThread,
} from "@/lib/api/chat";
import {
  type ChatAttachment,
  type ChatMessage,
  type ChatThread,
  keys,
  type Plan,
} from "@/lib/api/hooks";
import {
  type ChatEvent,
  type ChatMessageIn,
  ChatProblemError,
  ChatStreamDropped,
  type DoneEvent,
} from "@/lib/api/sse";
import { localISODate, localTime } from "@/lib/dates";

/**
 * The message being answered in this tab. `sending` until the server accepts it (`thread`),
 * `streaming` until `done`; `dropped` when the connection broke after the server had it (the
 * turn runs on: the thread is polled for the answer); `failed` when the server never confirmed
 * it (retry with the same client_id is safe) or the turn ended with an `error` event.
 */
export type LiveTurn = {
  clientId: string;
  text: string;
  phase: "sending" | "streaming" | "dropped" | "failed";
  threadId: number | null;
  userMessageId: number | null;
  status: string | null;
  streamed: string;
  attachments: ChatAttachment[];
  error: string | null;
};

export function startTurn(text: string, clientId: string): LiveTurn {
  return {
    clientId,
    text,
    phase: "sending",
    threadId: null,
    userMessageId: null,
    status: null,
    streamed: "",
    attachments: [],
    error: null,
  };
}

/** Fold one streamed event into the live turn (done/error are handled by the caller). */
export function applyEvent(turn: LiveTurn, event: ChatEvent): LiveTurn {
  switch (event.type) {
    case "thread":
      return {
        ...turn,
        phase: "streaming",
        threadId: event.thread_id,
        userMessageId: event.message_id,
      };
    case "status":
      return { ...turn, status: event.text };
    case "text":
      return { ...turn, status: null, streamed: turn.streamed + event.delta };
    case "text_reset":
      return { ...turn, streamed: "" };
    case "outcome":
    case "recipe":
      return { ...turn, attachments: [...turn.attachments, event] };
    default:
      return turn;
  }
}

/**
 * The stored thread has caught up with a turn the server accepted: nothing is pending and the
 * turn's message is there (with its reply), or the latest thread is another one by now.
 */
export function settled(
  thread: ChatThread | undefined,
  turn: Pick<LiveTurn, "threadId" | "userMessageId">,
): boolean {
  if (!thread || turn.userMessageId === null || thread.pending !== null) return false;
  return (
    thread.messages.some((m) => m.id === turn.userMessageId) ||
    (turn.threadId !== null && thread.thread_id !== turn.threadId)
  );
}

const UNREACHABLE = "Couldn't reach Larder. Check your connection and try again.";

/** The daily message limit was hit; sending works again at `until`. */
export type Limit = { until: string } | null;

/**
 * Chat state for the page: the stored thread (TanStack Query, the truth once a reply is
 * saved), the live turn streamed in this tab, the composer draft and the gate's refusals.
 */
export function useChat() {
  const qc = useQueryClient();
  const sendMessage = useChatSender();
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [limited, setLimited] = useState<Limit>(null);
  const [draft, setDraft] = useState("");
  const [earlier, setEarlier] = useState<{
    threadId: number | null;
    messages: ChatMessage[];
    hasMore: boolean;
  } | null>(null);

  const streaming = live?.phase === "sending" || live?.phase === "streaming";
  const dropped = live?.phase === "dropped" ? live : null;
  const thread = useChatThread(
    (t) => !streaming && (t?.pending != null || (dropped !== null && !settled(t, dropped))),
  );
  const newThread = useNewChatThread();
  const older = useEarlierMessages();
  const data = thread.data;

  // A reply saved while this tab wasn't streaming it (dropped stream, reload, other device)
  // replaces the live bubble as soon as the thread has it.
  const shownLive = live && !settled(data, live) ? live : null;
  const pending = shownLive ? null : (data?.pending ?? null);
  const busy = (shownLive !== null && shownLive.phase !== "failed") || pending !== null;

  const olderShown = earlier && earlier.threadId === data?.thread_id ? earlier : null;
  const messages = mergeMessages(olderShown?.messages ?? [], data?.messages ?? []);
  const hasMore = olderShown ? olderShown.hasMore : (data?.has_more ?? false);
  const atLimit = data ? data.messages_today >= data.daily_limit : false;

  // Coming back to the page: the reply may have arrived (or still be on its way).
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        void qc.invalidateQueries({ queryKey: keys.chatThread });
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [qc]);

  // The daily limit lifts at retry_at.
  useEffect(() => {
    if (!limited) return;
    const wait = Math.max(0, Date.parse(limited.until) - Date.now());
    const timer = setTimeout(() => {
      setLimited(null);
      void qc.invalidateQueries({ queryKey: keys.chatThread });
    }, wait);
    return () => clearTimeout(timer);
  }, [limited, qc]);

  // A chat turn made a newer plan than the one cached for /plan: refresh it.
  const latestPlanId = Math.max(0, ...messages.map((m) => m.plan_id ?? 0));
  useEffect(() => {
    if (!latestPlanId) return;
    const current = qc.getQueryData<Plan | null>(keys.currentPlan);
    if (current && current.id < latestPlanId) void qc.invalidateQueries({ queryKey: keys.plans });
  }, [latestPlanId, qc]);

  function refreshThread() {
    void qc.invalidateQueries({ queryKey: keys.chatThread });
  }

  function patchThread(patch: (old: ChatThread) => ChatThread) {
    qc.setQueryData<ChatThread>(keys.chatThread, (old) => (old ? patch(old) : old));
  }

  async function finish(turn: LiveTurn, done: DoneEvent) {
    // A thread refetch started before `done` would bring back the pending state.
    await qc.cancelQueries({ queryKey: keys.chatThread });
    const mine: ChatMessage[] =
      turn.userMessageId === null
        ? []
        : [
            {
              id: turn.userMessageId,
              role: "user",
              text: turn.text,
              created_at: new Date().toISOString(),
              plan_id: null,
              mode: null,
              offline_reason: null,
              attachments: [],
              suggestions: [],
            },
          ];
    patchThread((old) => {
      const same = turn.threadId === null || old.thread_id === turn.threadId;
      return {
        ...old,
        thread_id: turn.threadId ?? old.thread_id,
        messages: mergeMessages(same ? old.messages : [], mine, [done.message]),
        has_more: same ? old.has_more : false,
        pending: null,
        messages_today: done.messages_today,
      };
    });
    setLive(null);
  }

  function refused(turn: LiveTurn, error: ApiError) {
    setLive(null);
    const restore = () => setDraft((d) => d || turn.text);
    if (!(error instanceof ChatProblemError)) {
      restore();
      setNotice(error.messages.join(" ") || `Couldn't send your message (${error.status}).`);
      return;
    }
    const { code, retry_at } = error.problem;
    if (code === "duplicate") {
      refreshThread();
      return;
    }
    restore();
    if (code === "daily_limit") {
      setLimited({ until: retry_at ?? new Date(Date.now() + 60_000).toISOString() });
    } else if (code === "busy") {
      setNotice("Still answering your last message. Send this once it's done.");
      refreshThread();
    } else if (code === "thread_not_found") {
      setNotice("That conversation has gone. Send your message again to carry on here.");
      setEarlier(null);
      refreshThread();
    } else {
      setNotice(error.messages.join(" ") || "Check your device's date and time, then try again.");
    }
  }

  async function submit(text: string, clientId: string) {
    const body: ChatMessageIn = {
      text,
      client_id: clientId,
      thread_id: data?.thread_id ?? null,
      today: localISODate(),
      local_time: localTime(),
    };
    let turn = startTurn(text, clientId);
    setLive(turn);
    setNotice(null);
    const onEvent = (event: ChatEvent) => {
      turn = applyEvent(turn, event);
      setLive(turn);
      if (event.type === "thread") {
        patchThread((old) => ({
          ...old,
          llm_available: event.mode === "llm",
          offline_reason: event.mode === "llm" ? null : event.offline_reason,
        }));
      } else if (event.type === "outcome" && event.plan_id != null) {
        // The new version is saved before this event is sent.
        void qc.invalidateQueries({ queryKey: keys.plans });
      }
    };
    try {
      const last = await sendMessage(body, onEvent);
      if (last.type === "done") {
        await finish(turn, last);
      } else {
        setLive({ ...turn, phase: "failed", error: last.message });
        refreshThread();
      }
    } catch (error) {
      if (error instanceof ApiError) {
        refused(turn, error);
      } else if (error instanceof ChatStreamDropped && turn.userMessageId !== null) {
        setLive({ ...turn, phase: "dropped", status: null });
        refreshThread();
      } else {
        setLive({ ...turn, phase: "failed", status: null, error: UNREACHABLE });
      }
    }
  }

  const canSend = !busy && !limited && !atLimit && !newThread.isPending;

  return {
    thread,
    messages,
    hasMore,
    loadingEarlier: older.isPending,
    loadEarlier() {
      const first = messages[0];
      if (!first) return;
      older.mutate(first.id, {
        onSuccess: (page) =>
          setEarlier((prev) => ({
            threadId: page.thread_id,
            messages: mergeMessages(
              page.messages,
              prev?.threadId === page.thread_id ? prev.messages : [],
            ),
            hasMore: page.has_more,
          })),
      });
    },
    live: shownLive,
    pending,
    busy,
    canSend,
    notice,
    limited,
    atLimit,
    draft,
    setDraft,
    send(text: string) {
      const trimmed = text.trim();
      if (!trimmed || !canSend) return;
      setDraft("");
      void submit(trimmed, crypto.randomUUID());
    },
    /** Resend a message the server never confirmed, with the same id (safe to repeat). */
    retry() {
      if (live?.phase === "failed" && !busy) void submit(live.text, live.clientId);
    },
    startNewThread() {
      newThread.mutate(undefined, {
        onSuccess: () => {
          setEarlier(null);
          setLive(null);
          setNotice(null);
        },
      });
    },
    newThreadPending: newThread.isPending,
  };
}

export type Chat = ReturnType<typeof useChat>;
