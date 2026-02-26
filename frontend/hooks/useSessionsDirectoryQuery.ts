import { useCallback, useMemo } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { listSessionsPage, type SessionListItem } from "@/lib/api/sessions";
import { queryKeys } from "@/lib/queryKeys";
import { type UnifiedSessionSource } from "@/lib/sessionIds";

const DEFAULT_PAGE_SIZE = 50;

export function useSessionsDirectoryQuery(options?: {
  source?: UnifiedSessionSource;
  agentId?: string | null;
  size?: number;
  enabled?: boolean;
}) {
  const pageSize =
    typeof options?.size === "number" && options.size > 0
      ? Math.floor(options.size)
      : DEFAULT_PAGE_SIZE;
  const normalizedAgentId =
    typeof options?.agentId === "string" && options.agentId.trim().length > 0
      ? options.agentId.trim()
      : null;
  const queryKey = useMemo(
    () =>
      queryKeys.sessions.directory({
        source: options?.source,
        agentId: normalizedAgentId ?? undefined,
        size: pageSize,
      }),
    [normalizedAgentId, options?.source, pageSize],
  );

  const fetchPage = useCallback(
    async (page: number) => {
      const result = await listSessionsPage({
        page,
        size: pageSize,
        ...(options?.source ? { source: options.source } : {}),
        ...(normalizedAgentId ? { agent_id: normalizedAgentId } : {}),
      });

      return { items: result.items, nextPage: result.nextPage };
    },
    [normalizedAgentId, options?.source, pageSize],
  );

  const query = usePaginatedList<SessionListItem>({
    queryKey,
    fetchPage,
    getKey: (item) => item.conversationId,
    errorTitle: "Load sessions failed",
    fallbackMessage: "Load failed.",
    enabled: options?.enabled ?? true,
  });

  const refresh = useCallback(async () => {
    await query.loadFirstPage("refreshing");
  }, [query.loadFirstPage]);

  return {
    ...query,
    refresh,
  };
}
