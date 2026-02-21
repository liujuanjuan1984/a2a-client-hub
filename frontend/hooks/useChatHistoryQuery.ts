import { useCallback, useMemo } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { listSessionMessagesPage } from "@/lib/api/sessions";
import { queryKeys } from "@/lib/queryKeys";
import {
  mapSessionMessagesToChatMessages,
  type SessionMessageItem,
} from "@/lib/sessionHistory";

export function useSessionHistoryQuery(options: {
  conversationId?: string;
  enabled: boolean;
  paused?: boolean;
}) {
  const { conversationId, enabled, paused = false } = options;

  const fetchPage = useCallback(
    async (page: number) => {
      if (!conversationId) {
        throw new Error("Conversation id is required.");
      }
      return await listSessionMessagesPage(conversationId, { page, size: 100 });
    },
    [conversationId],
  );

  const query = usePaginatedList<SessionMessageItem>({
    queryKey: queryKeys.history.chat(conversationId ?? "missing"),
    fetchPage,
    getKey: (item) => item.id ?? `${item.created_at}:${item.role}`,
    errorTitle: "Load history failed",
    fallbackMessage: "Load failed.",
    enabled: enabled && Boolean(conversationId) && !paused,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: true,
    staleTime: 0,
  });

  const messages = useMemo(() => {
    if (!conversationId) {
      return [];
    }
    return mapSessionMessagesToChatMessages(query.items, conversationId);
  }, [query.items, conversationId]);

  return {
    ...query,
    messages,
  };
}
