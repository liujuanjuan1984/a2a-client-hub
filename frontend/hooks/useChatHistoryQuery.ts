import { useCallback, useMemo } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { listOpencodeSessionMessagesPage } from "@/lib/api/opencodeSessions";
import { listSessionMessagesPage } from "@/lib/api/sessions";
import {
  getOpencodeMessageId,
  getOpencodeMessageRole,
  getOpencodeMessageTimestamp,
} from "@/lib/opencodeAdapters";
import { mapOpencodeMessagesToChatMessages } from "@/lib/opencodeChatAdapters";
import { queryKeys } from "@/lib/queryKeys";
import {
  mapSessionMessagesToChatMessages,
  type SessionMessageItem,
} from "@/lib/sessionHistory";

export function useSessionHistoryQuery(options: {
  sessionId?: string;
  enabled: boolean;
}) {
  const { sessionId, enabled } = options;

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
    enabled: enabled && Boolean(sessionId),
  });

  const messages = useMemo(() => {
    if (!sessionId) {
      return [];
    }
    return mapSessionMessagesToChatMessages(query.items, sessionId).slice(-500);
  }, [query.items, sessionId]);

  return {
    ...query,
    messages,
  };
}

export function useOpencodeHistoryQuery(options: {
  agentId?: string;
  sessionId?: string;
  source: "personal" | "shared";
  enabled: boolean;
}) {
  const { agentId, sessionId, source, enabled } = options;

  const fetchPage = useCallback(
    async (page: number) => {
      if (!agentId || !sessionId) {
        throw new Error("Agent and OpenCode session are required.");
      }
      return await listOpencodeSessionMessagesPage(agentId, sessionId, {
        page,
        size: 100,
        source,
      });
    },
    [agentId, sessionId, source],
  );

  const query = usePaginatedList<unknown>({
    queryKey: queryKeys.history.opencode(
      agentId ?? "missing-agent",
      sessionId ?? "missing-session",
      source,
    ),
    fetchPage,
    getKey: (item) =>
      `${getOpencodeMessageId(item)}:${getOpencodeMessageTimestamp(item) ?? ""}:${getOpencodeMessageRole(item)}`,
    errorTitle: "Load history failed",
    fallbackMessage: "Load failed.",
    enabled: enabled && Boolean(agentId) && Boolean(sessionId),
  });

  const messages = useMemo(() => {
    return mapOpencodeMessagesToChatMessages(query.items)
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt))
      .slice(-500);
  }, [query.items]);

  return {
    ...query,
    messages,
  };
}
