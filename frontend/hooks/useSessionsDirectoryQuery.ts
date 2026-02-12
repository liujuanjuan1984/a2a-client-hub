import { useCallback, useRef } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import {
  listOpencodeSessionsDirectoryPage,
  type OpencodeSessionDirectoryItem,
} from "@/lib/api/opencodeSessions";
import { queryKeys } from "@/lib/queryKeys";

export function useSessionsDirectoryQuery() {
  const refreshNextRef = useRef(false);

  const fetchPage = useCallback(async (page: number) => {
    const refresh = page === 1 && refreshNextRef.current;
    if (refresh) {
      refreshNextRef.current = false;
    }

    const result = await listOpencodeSessionsDirectoryPage({
      page,
      size: 50,
      refresh,
    });

    return { items: result.items, nextPage: result.nextPage };
  }, []);

  const query = usePaginatedList<OpencodeSessionDirectoryItem>({
    queryKey: queryKeys.sessions.directory(),
    fetchPage,
    getKey: (item) => `${item.agent_id}:${item.session_id}`,
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
