"use client";

import { useAuth } from "@clerk/nextjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { PUBLIC_API_URL, unwrap, useApi } from "./browser";
import { type ChatMessage, type ChatThread, keys } from "./hooks";
import { type ChatEvent, type ChatMessageIn, sendChatMessage } from "./sse";

/** How often the thread is reloaded while a reply is being worked on elsewhere. */
export const POLL_MS = 2_000;

/** Messages by id, oldest first, without duplicates (later copies win). */
export function mergeMessages(...lists: ChatMessage[][]): ChatMessage[] {
  const byId = new Map<number, ChatMessage>();
  for (const m of lists.flat()) byId.set(m.id, m);
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

/**
 * The latest thread. `poll`: reload every POLL_MS (a reply is pending, or a dropped stream is
 * waiting for its answer). Always refetched on mount; focus refetches are left to the page,
 * which listens for `visibilitychange` itself.
 */
export function useChatThread(poll: (thread: ChatThread | undefined) => boolean) {
  const api = useApi();
  return useQuery({
    queryKey: keys.chatThread,
    queryFn: async () => unwrap(await api.GET("/chat/thread")),
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => (poll(query.state.data) ? POLL_MS : false),
  });
}

/** Start a fresh conversation; the old one is kept (export) but no longer shown. */
export function useNewChatThread() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST("/chat/threads")),
    onSuccess: async (thread) => {
      await qc.cancelQueries({ queryKey: keys.chatThread });
      qc.setQueryData(keys.chatThread, thread);
    },
  });
}

/** One page of older messages of the latest thread, before `beforeId`. */
export function useEarlierMessages() {
  const api = useApi();
  return useMutation({
    mutationFn: async (beforeId: number) =>
      unwrap(await api.GET("/chat/thread", { params: { query: { before_id: beforeId } } })),
  });
}

/** `sendChatMessage` bound to the API URL and the signed-in user's session token. */
export function useChatSender() {
  const { getToken } = useAuth();
  return useCallback(
    async (body: ChatMessageIn, onEvent: (event: ChatEvent) => void, signal?: AbortSignal) =>
      sendChatMessage(PUBLIC_API_URL, await getToken(), body, onEvent, signal),
    [getToken],
  );
}
