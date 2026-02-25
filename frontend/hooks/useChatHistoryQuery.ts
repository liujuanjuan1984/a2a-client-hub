import { useCallback, useMemo } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { type ChatMessage } from "@/lib/api/chat-utils";
import { listSessionMessagesPage } from "@/lib/api/sessions";
import { queryKeys } from "@/lib/queryKeys";
import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";

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
      const response = await listSessionMessagesPage(conversationId, {
        page,
        size: 100,
      });
      return {
        items: mapSessionMessagesToChatMessages(response.items),
        nextPage: response.nextPage,
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

  const messages = useMemo(() => {
    if (!conversationId) {
      return [];
    }
    return [...query.items].sort((left, right) =>
      left.createdAt.localeCompare(right.createdAt),
    );
  }, [query.items, conversationId]);

  return {
    ...query,
    messages,
  };
}
