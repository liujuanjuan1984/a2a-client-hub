import { useChatHistory } from "./useChatHistory";
import { useChatScreenFocusEffects } from "./useChatScreenFocusEffects";
import { useChatScroll } from "./useChatScroll";
import { useChatScrollRefs } from "./useChatScrollRefs";

export function useChatDisplayState({
  conversationId,
  streamState,
}: {
  conversationId?: string;
  streamState?: string;
}) {
  const scrollRefs = useChatScrollRefs();

  const history = useChatHistory(
    conversationId,
    streamState,
    scrollRefs.scrollOffsetRef,
    scrollRefs.contentHeightRef,
  );

  const scroll = useChatScroll(scrollRefs, streamState, history.loadMore);

  useChatScreenFocusEffects({
    conversationId,
    scheduleStickToBottom: scroll.scheduleStickToBottom,
    forceScrollToBottomRef: scroll.forceScrollToBottomRef,
    shouldStickToBottomRef: scroll.shouldStickToBottomRef,
    messages: history.messages,
  });

  return { history, scroll };
}
