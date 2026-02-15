import { useCallback, useRef } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { listSessionsPage, type SessionListItem } from "@/lib/api/sessions";
import { queryKeys } from "@/lib/queryKeys";

export function useSessionsDirectoryQuery() {
  const refreshNextRef = useRef(false);

  const fetchPage = useCallback(async (page: number) => {
    const refresh = page === 1 && refreshNextRef.current;
    if (refresh) {
      refreshNextRef.current = false;
    }

    const result = await listSessionsPage({
      page,
      size: 50,
      refresh,
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
    refreshNextRef.current = true;
    await query.loadFirstPage("refreshing");
  }, [query.loadFirstPage]);

  return {
    ...query,
    refresh,
  };
}
