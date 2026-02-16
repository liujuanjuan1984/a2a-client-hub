import { useCallback } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { listSessionsPage, type SessionListItem } from "@/lib/api/sessions";
import { queryKeys } from "@/lib/queryKeys";

export function useSessionsDirectoryQuery() {
  const fetchPage = useCallback(async (page: number) => {
    const result = await listSessionsPage({
      page,
      size: 50,
    });

    return { items: result.items, nextPage: result.nextPage };
  }, []);

  const query = usePaginatedList<SessionListItem>({
    queryKey: queryKeys.sessions.directory(),
    fetchPage,
    getKey: (item) => item.conversationId,
    errorTitle: "Load sessions failed",
    fallbackMessage: "Load failed.",
  });

  const refresh = useCallback(async () => {
    await query.loadFirstPage("refreshing");
  }, [query.loadFirstPage]);

  return {
    ...query,
    refresh,
  };
}
