import { useCallback } from "react";

import { useSessionHistoryQuery } from "@/hooks/useChatHistoryQuery";
import { useMessageBlockLoader } from "@/hooks/useMessageBlockLoader";
import { useRefreshOnFocus } from "@/hooks/useRefreshOnFocus";
import { useChatStore } from "@/store/chat";

export function useMessageState(
  conversationId: string | undefined,
  streamState?: string | undefined,
) {
  // If streamState is not provided, we subscribe to it.
  // This allows the hook to be used independently or with a derived value.
  const sessionStreamState = useChatStore((state) =>
    conversationId ? state.sessions[conversationId]?.streamState : undefined,
  );

  const effectiveStreamState = streamState ?? sessionStreamState;
  const historyPaused = effectiveStreamState === "streaming";

  const sessionHistoryQuery = useSessionHistoryQuery({
    conversationId,
    enabled: Boolean(conversationId),
    paused: historyPaused,
  });

  useRefreshOnFocus(sessionHistoryQuery.loadFirstPage);

  const messages = sessionHistoryQuery.messages;
  const historyLoading = sessionHistoryQuery.loading;
  const historyLoadingMore = sessionHistoryQuery.loadingMore;
  const historyNextPage = sessionHistoryQuery.nextPage;
  const historyError =
    sessionHistoryQuery.error instanceof Error
      ? sessionHistoryQuery.error.message
      : null;

  const { handleLoadBlockContent } = useMessageBlockLoader(conversationId);

  const loadMore = useCallback(async () => {
    if (!conversationId) return;
    if (historyPaused) return;
    if (typeof historyNextPage !== "number") return;
    if (historyLoadingMore) return;

    try {
      await sessionHistoryQuery.loadMore();
    } catch {
      // Error handled by query
    }
  }, [
    historyLoadingMore,
    historyNextPage,
    historyPaused,
    sessionHistoryQuery,
    conversationId,
  ]);

  return {
    messages,
    loading: historyLoading,
    loadingMore: historyLoadingMore,
    nextPage: historyNextPage,
    paused: historyPaused,
    error: historyError,
    loadMore,
    handleLoadBlockContent,
  };
}
