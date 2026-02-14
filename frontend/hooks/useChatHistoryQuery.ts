import { useCallback, useMemo } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { listSessionMessagesPage } from "@/lib/api/sessions";
import { queryKeys } from "@/lib/queryKeys";
import {
  mapSessionMessagesToChatMessages,
  type SessionMessageItem,
} from "@/lib/sessionHistory";

export function useSessionHistoryQuery(options: {
  sessionId?: string;
  enabled: boolean;
  paused?: boolean;
}) {
  const { sessionId, enabled, paused = false } = options;

  const fetchPage = useCallback(
    async (page: number) => {
      if (!sessionId) {
        throw new Error("Session id is required.");
      }
      return await listSessionMessagesPage(sessionId, { page, size: 100 });
    },
    [sessionId],
  );

  const query = usePaginatedList<SessionMessageItem>({
    queryKey: queryKeys.history.chat(sessionId ?? "missing"),
    fetchPage,
    getKey: (item) =>
      `${item.id ?? "no-id"}:${item.created_at}:${item.role}:${item.content}`,
    errorTitle: "Load history failed",
    fallbackMessage: "Load failed.",
    enabled: enabled && Boolean(sessionId) && !paused,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const messages = useMemo(() => {
    if (!sessionId) {
      return [];
    }
    return mapSessionMessagesToChatMessages(query.items, sessionId);
  }, [query.items, sessionId]);

  return {
    ...query,
    messages,
  };
}
