import { useCallback, useEffect, useMemo, useRef } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { type ChatMessage } from "@/lib/api/chat-utils";
import { listSessionTimelinePage } from "@/lib/api/sessions";
import { queryKeys } from "@/lib/queryKeys";
import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";

const TIMELINE_PAGE_LIMIT = 8;

const timelineCursorStore = new Map<string, Map<number, string | null>>();

const resolveCursorMap = (
  conversationId: string,
): Map<number, string | null> => {
  const existing = timelineCursorStore.get(conversationId);
  if (existing) {
    if (!existing.has(1)) {
      existing.set(1, null);
    }
    return existing;
  }
  const created = new Map<number, string | null>([[1, null]]);
  timelineCursorStore.set(conversationId, created);
  return created;
};

const compareMessagesByTimeline = (left: ChatMessage, right: ChatMessage) => {
  const createdAtDiff = left.createdAt.localeCompare(right.createdAt);
  if (createdAtDiff !== 0) {
    return createdAtDiff;
  }
  const rolePriority = (role: ChatMessage["role"]) => {
    if (role === "user") return 0;
    if (role === "agent") return 1;
    return 2;
  };
  const roleDiff = rolePriority(left.role) - rolePriority(right.role);
  if (roleDiff !== 0) {
    return roleDiff;
  }
  return left.id.localeCompare(right.id);
};

export function useSessionHistoryQuery(options: {
  conversationId?: string;
  enabled: boolean;
  paused?: boolean;
}) {
  const { conversationId, enabled, paused = false } = options;
  const cursorByPageRef = useRef<Map<number, string | null>>(
    new Map<number, string | null>([[1, null]]),
  );

  useEffect(() => {
    if (!conversationId) {
      cursorByPageRef.current = new Map<number, string | null>([[1, null]]);
      return;
    }
    cursorByPageRef.current = resolveCursorMap(conversationId);
    cursorByPageRef.current.set(1, null);
  }, [conversationId]);

  const fetchPage = useCallback(
    async (page: number) => {
      if (!conversationId) {
        throw new Error("Conversation id is required.");
      }
      const resolvedPage =
        Number.isFinite(page) && page > 0 ? Math.floor(page) : 1;
      const before =
        resolvedPage > 1
          ? (cursorByPageRef.current.get(resolvedPage) ?? null)
          : null;
      const response = await listSessionTimelinePage(conversationId, {
        before,
        limit: TIMELINE_PAGE_LIMIT,
      });
      const nextBefore =
        typeof response.pageInfo.nextBefore === "string" &&
        response.pageInfo.nextBefore.trim().length > 0
          ? response.pageInfo.nextBefore.trim()
          : null;
      const nextPage =
        response.pageInfo.hasMoreBefore && nextBefore
          ? resolvedPage + 1
          : undefined;
      if (nextPage && nextBefore) {
        cursorByPageRef.current.set(nextPage, nextBefore);
      } else {
        cursorByPageRef.current.delete(resolvedPage + 1);
      }
      return {
        items: mapSessionMessagesToChatMessages(response.items, {
          keepEmptyMessages: true,
        }),
        nextPage,
      };
    },
    [conversationId],
  );

  const query = usePaginatedList<ChatMessage>({
    queryKey: queryKeys.history.chat(conversationId ?? "missing"),
    fetchPage,
    getKey: (item) => item.id.trim(),
    errorTitle: "Load history failed",
    fallbackMessage: "Load failed.",
    enabled: enabled && Boolean(conversationId) && !paused,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchOnMount: true,
    staleTime: 0,
  });

  const messages = useMemo(
    () => [...query.items].sort(compareMessagesByTimeline),
    [query.items],
  );

  return {
    ...query,
    messages,
  };
}
