import { cn } from "cn";
import { LoaderCircleIcon, RotateCcwIcon, TriangleAlertIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ChatAttachment, ChatMessage } from "@/lib/api/hooks";

import { Attachment } from "./outcome-card";
import type { LiveTurn } from "./use-chat";
import { APP_NAME } from "@/lib/brand";

function UserBubble({ text, children }: { text: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <p className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-3 py-2 break-words whitespace-pre-line text-primary-foreground">
        <span className="sr-only">You: </span>
        <span>{text}</span>
      </p>
      {children}
    </div>
  );
}

function AssistantBubble({
  text,
  attachments,
  today,
  busy = false,
  children,
}: {
  text: string;
  attachments: ChatAttachment[];
  today: string;
  busy?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-2" aria-busy={busy || undefined}>
      {text || children ? (
        <div className="max-w-[85%] rounded-2xl rounded-bl-md bg-muted px-3 py-2">
          <span className="sr-only">{APP_NAME}: </span>
          {text ? <p className="break-words whitespace-pre-line">{text}</p> : null}
          {children}
        </div>
      ) : null}
      {attachments.length ? (
        <div className="flex w-full flex-col gap-2 pr-6">
          {attachments.map((a, i) => (
            <Attachment key={`${a.type}-${i}`} attachment={a} today={today} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** A "working on it" line: spinner plus words, announced politely. */
function StatusLine({ text }: { text: string }) {
  return (
    <p role="status" className="flex items-center gap-1.5 text-sm text-muted-foreground">
      <LoaderCircleIcon aria-hidden className="size-3.5 animate-spin" />
      {text}
    </p>
  );
}

export function StoredMessage({ message, today }: { message: ChatMessage; today: string }) {
  if (message.role === "user") return <UserBubble text={message.text} />;
  return <AssistantBubble text={message.text} attachments={message.attachments} today={today} />;
}

/** The turn streaming in this tab: optimistic user bubble, then the reply as it arrives. */
export function LiveReply({
  turn,
  showUser,
  today,
  onRetry,
}: {
  turn: LiveTurn;
  showUser: boolean;
  today: string;
  onRetry: () => void;
}) {
  const unconfirmed = turn.phase === "failed" && turn.userMessageId === null;
  return (
    <>
      {showUser ? (
        <UserBubble text={turn.text}>
          {unconfirmed ? (
            <div role="alert" className="flex flex-col items-end gap-1 text-xs text-destructive">
              <span className="flex items-center gap-1">
                <TriangleAlertIcon aria-hidden className="size-3.5" />
                {turn.error}
              </span>
              <Button size="sm" variant="outline" onClick={onRetry}>
                <RotateCcwIcon aria-hidden />
                Try again
              </Button>
            </div>
          ) : null}
        </UserBubble>
      ) : null}
      {unconfirmed ? null : (
        <AssistantBubble
          text={turn.streamed}
          attachments={turn.attachments}
          today={today}
          busy={turn.phase !== "failed"}
        >
          {turn.phase === "failed" ? (
            <p role="alert" className="flex items-center gap-1.5 text-sm text-destructive">
              <TriangleAlertIcon aria-hidden className="size-3.5 shrink-0" />
              {turn.error}
            </p>
          ) : turn.phase === "dropped" ? (
            <StatusLine text="Connection lost. Waiting for the reply…" />
          ) : turn.status || !turn.streamed ? (
            <div className={cn(turn.streamed && "mt-1")}>
              <StatusLine text={turn.status ?? "Thinking…"} />
            </div>
          ) : null}
        </AssistantBubble>
      )}
    </>
  );
}

/** A reply the server is still working on (sent from another tab, or before a reload). */
export function PendingReply({ today }: { today: string }) {
  return (
    <AssistantBubble text="" attachments={[]} today={today} busy>
      <StatusLine text="Still working on your last message…" />
    </AssistantBubble>
  );
}
