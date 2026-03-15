import { useMessageState } from "./useMessageState";

export function useChatHistory(
  conversationId: string | undefined,
  streamState: string | undefined,
  scrollOffsetRef: React.MutableRefObject<number>,
  contentHeightRef: React.MutableRefObject<number>,
) {
  const historyPaused = streamState === "streaming";
  const messageState = useMessageState(conversationId, historyPaused);

  return {
    messages: messageState.messages,
    loading: messageState.historyLoading,
    loadingMore: messageState.historyLoadingMore,
    nextPage: messageState.historyNextPage,
    paused: historyPaused,
    error: messageState.historyError,
    loadMore: () =>
      messageState.loadEarlierHistory(
        scrollOffsetRef.current,
        contentHeightRef.current,
      ),
    handleLoadBlockContent: messageState.handleLoadBlockContent,
  };
}
