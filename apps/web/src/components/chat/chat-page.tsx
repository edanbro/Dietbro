"use client";

import { InfoIcon, LoaderCircleIcon, SquarePenIcon, TimerIcon } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { EmptyIllustration } from "@/components/empty-state";
import { ErrorAlert } from "@/components/form-bits";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { ChatThread } from "@/lib/api/hooks";
import { formatWhen, localISODate } from "@/lib/dates";

import { Composer } from "./composer";
import { LiveReply, PendingReply, StoredMessage } from "./messages";
import { type Chat, useChat } from "./use-chat";
import { APP_NAME } from "@/lib/brand";

/** The offline parser's examples (larder_llm.reply.HELP_TEXT): every one of them parses. */
export const EXAMPLES = [
  "skip dinner tonight",
  "had pizza for lunch",
  "craving something spicy on Friday",
  "swap Thursday's dinner",
];

/** Why replies are simple right now (no model key, budget spent, model down). */
export function OfflineBanner({ thread }: { thread: ChatThread }) {
  if (thread.llm_available) return null;
  const reason = thread.offline_reason ?? "no_key";
  const title =
    reason === "budget"
      ? thread.llm_resets_at
        ? `AI replies paused until ${formatWhen(thread.llm_resets_at)}`
        : "AI replies paused"
      : reason === "model_error"
        ? "Simple replies: the AI isn't responding"
        : "Simple replies: no AI key";
  // A quiet note, not a warning: the chat still changes the plan, just with simpler words.
  return (
    <p
      role="note"
      className="flex items-start gap-2 rounded-xl bg-muted/60 px-3 py-2 text-xs text-muted-foreground"
    >
      <InfoIcon aria-hidden className="mt-px size-3.5 shrink-0" />
      <span>
        <span className="font-medium text-foreground">{title}.</span>{" "}
        {reason === "budget" ? "You've used your AI chat allowance for now. " : null}
        {APP_NAME} follows short, plain requests like &ldquo;skip dinner tonight&rdquo; or &ldquo;had
        pizza for lunch&rdquo;.
      </span>
    </p>
  );
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <section className="flex flex-col items-center gap-3 px-2 py-8 text-center">
      <EmptyIllustration art="chat" />
      <h2 className="text-xl font-semibold">Tell {APP_NAME} what changed</h2>
      <p className="max-w-sm text-sm text-pretty text-muted-foreground">
        A craving, food you ate, a meal you&apos;ll skip: {APP_NAME} re-plans the rest of your week
        around it, still within your goals and allergies.
      </p>
      <div className="mt-2 flex flex-col items-center gap-2">
        <p id="chat-examples" className="text-xs text-muted-foreground">
          Try:
        </p>
        <ul aria-labelledby="chat-examples" className="flex flex-wrap justify-center gap-2">
          {EXAMPLES.map((e) => (
            <li key={e}>
              <Button
                variant="outline"
                size="sm"
                className="h-auto rounded-full py-1 whitespace-normal"
                onClick={() => onPick(e)}
              >
                {e}
              </Button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Suggestions({ items, chat }: { items: string[]; chat: Chat }) {
  if (!items.length) return null;
  return (
    <ul aria-label="Suggested replies" className="flex flex-wrap gap-2">
      {items.map((s) => (
        <li key={s}>
          <Button
            variant="outline"
            size="sm"
            className="h-auto rounded-full py-1 whitespace-normal"
            disabled={!chat.canSend}
            onClick={() => chat.send(s)}
          >
            {s}
          </Button>
        </li>
      ))}
    </ul>
  );
}

function LimitNote({ chat, thread }: { chat: Chat; thread: ChatThread }) {
  const left = thread.daily_limit - thread.messages_today;
  if (chat.limited || chat.atLimit) {
    return (
      <p role="status" className="flex items-start gap-1.5 text-sm text-muted-foreground">
        <TimerIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
        <span>
          You&apos;ve reached today&apos;s limit of {thread.daily_limit} messages.{" "}
          {chat.limited
            ? `You can send again at ${formatWhen(chat.limited.until)}.`
            : "Try again later."}
        </span>
      </p>
    );
  }
  if (left > 5) return null;
  return (
    <p className="text-xs text-muted-foreground">
      {left} {left === 1 ? "message" : "messages"} left today
    </p>
  );
}

function ChatSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-busy>
      <Skeleton className="h-8 w-24" />
      <Skeleton className="ml-auto h-10 w-2/3 rounded-2xl" />
      <Skeleton className="h-20 w-3/4 rounded-2xl" />
    </div>
  );
}

/** The chat screen: the latest thread, the reply streaming in, and the composer. */
export function ChatPage() {
  const chat = useChat();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const params = useSearchParams();
  const router = useRouter();
  const prompt = params.get("prompt");
  const { setDraft } = chat;
  useEffect(() => {
    if (!prompt) return;
    setDraft((d) => d || prompt.slice(0, 500));
    router.replace("/chat");
  }, [prompt, router, setDraft]);
  const endRef = useRef<HTMLDivElement>(null);
  const { thread, live, messages } = chat;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, live?.streamed, live?.status, live?.attachments.length, chat.pending]);

  // A failed poll keeps the conversation on screen; only a first load that fails shows it.
  const data = thread.data;
  if (!data) {
    return thread.error ? (
      <ErrorAlert error={thread.error} onRetry={() => void thread.refetch()} />
    ) : (
      <ChatSkeleton />
    );
  }

  const today = localISODate();
  const last = messages.at(-1);
  const suggestions =
    !live && !chat.pending && last?.role === "assistant" ? last.suggestions : [];
  const empty = !messages.length && !live && !chat.pending;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
        {messages.length ? (
          <Button
            variant="outline"
            size="sm"
            disabled={chat.busy || chat.newThreadPending}
            onClick={chat.startNewThread}
          >
            <SquarePenIcon aria-hidden />
            New chat
          </Button>
        ) : null}
      </div>
      <OfflineBanner thread={data} />

      {empty ? (
        <EmptyState
          onPick={(text) => {
            chat.setDraft(text);
            inputRef.current?.focus();
          }}
        />
      ) : (
        <div role="log" aria-label="Conversation" className="flex flex-col gap-3">
          {chat.hasMore ? (
            <Button
              variant="ghost"
              size="sm"
              className="self-center"
              disabled={chat.loadingEarlier}
              onClick={chat.loadEarlier}
            >
              {chat.loadingEarlier ? (
                <LoaderCircleIcon aria-hidden className="animate-spin" />
              ) : null}
              Show earlier messages
            </Button>
          ) : null}
          {messages.map((m) => (
            <StoredMessage key={m.id} message={m} today={today} />
          ))}
          {live ? (
            <LiveReply
              turn={live}
              showUser={!messages.some((m) => m.id === live.userMessageId)}
              today={today}
              onRetry={chat.retry}
            />
          ) : chat.pending ? (
            <PendingReply today={today} />
          ) : null}
          <Suggestions items={suggestions} chat={chat} />
        </div>
      )}

      {chat.notice ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{chat.notice}</AlertDescription>
        </Alert>
      ) : null}
      <LimitNote chat={chat} thread={data} />
      {/* Scrolled to on new content; its margin keeps the end clear of the composer and nav. */}
      <div ref={endRef} aria-hidden className="scroll-mb-32" />
      {/* Room for the composer pinned above the bottom nav. */}
      <div aria-hidden className="h-16 shrink-0" />
      <Composer chat={chat} inputRef={inputRef} />
    </div>
  );
}
