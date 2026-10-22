"use client";

import { ArrowUpIcon, LoaderCircleIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { Chat } from "./use-chat";
import { APP_NAME } from "@/lib/brand";

/**
 * The message box, pinned above the bottom nav (on desktop, to the bottom of the page column). Enter sends (Shift+Enter for a new line);
 * typing stays possible while a reply streams, sending doesn't.
 */
export function Composer({
  chat,
  inputRef,
}: {
  chat: Chat;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const blocked = chat.limited !== null || chat.atLimit;
  const canSubmit = chat.canSend && chat.draft.trim() !== "";
  return (
    <form
      aria-label="Send a message"
      onSubmit={(e) => {
        e.preventDefault();
        chat.send(chat.draft);
      }}
      className="fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-10 border-t bg-background/95 backdrop-blur lg:bottom-0 lg:left-64"
    >
      <div className="mx-auto flex max-w-md items-end gap-2 px-4 py-2 lg:max-w-4xl lg:px-10 lg:py-3">
        <label htmlFor="chat-message" className="sr-only">
          Message
        </label>
        <textarea
          id="chat-message"
          ref={inputRef}
          value={chat.draft}
          onChange={(e) => chat.setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (canSubmit) chat.send(chat.draft);
            }
          }}
          rows={1}
          maxLength={1000}
          disabled={blocked}
          enterKeyHint="send"
          placeholder={blocked ? "Daily limit reached" : `Tell ${APP_NAME} what changed…`}
          className="max-h-32 min-h-10 flex-1 resize-none rounded-2xl border border-input bg-transparent px-3 py-2 text-base outline-none field-sizing-content placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30"
        />
        <Button
          type="submit"
          size="icon-lg"
          className="size-10 rounded-full"
          aria-label="Send"
          disabled={!canSubmit}
        >
          {chat.busy ? (
            <LoaderCircleIcon aria-hidden className="animate-spin" />
          ) : (
            <ArrowUpIcon aria-hidden />
          )}
        </Button>
      </div>
    </form>
  );
}
