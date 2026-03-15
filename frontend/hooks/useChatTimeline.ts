import { useChatScroll } from "./useChatScroll";
import { useMessageState } from "./useMessageState";

export function useChatTimeline({
  conversationId,
  streamState,
}: {
  conversationId: string | undefined;
  streamState: string | undefined;
}) {
  const history = useMessageState(conversationId);

  const scroll = useChatScroll({
    conversationId,
    streamState,
    messages: history.messages,
    onLoadEarlier: history.loadMore,
  });

  return {
    history,
    scroll,
  };
}
