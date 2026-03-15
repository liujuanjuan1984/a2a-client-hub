import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef } from "react";

import { type ChatMessage } from "@/lib/api/chat-utils";

export function useChatScreenFocusEffects({
  conversationId,
  scheduleStickToBottom,
  forceScrollToBottomRef,
  shouldStickToBottomRef,
  messages,
}: {
  conversationId: string | undefined;
  scheduleStickToBottom: (animated: boolean) => void;
  forceScrollToBottomRef: React.MutableRefObject<boolean>;
  shouldStickToBottomRef: React.MutableRefObject<boolean>;
  messages: ChatMessage[];
}) {
  const isInitialLoadRef = useRef(true);
  const suppressAutoScrollRef = useRef(false);

  useFocusEffect(
    useCallback(() => {
      if (!conversationId) {
        return;
      }
      forceScrollToBottomRef.current = true;
      shouldStickToBottomRef.current = true;
      scheduleStickToBottom(true);
    }, [
      conversationId,
      forceScrollToBottomRef,
      scheduleStickToBottom,
      shouldStickToBottomRef,
    ]),
  );

  useEffect(() => {
    if (suppressAutoScrollRef.current) {
      suppressAutoScrollRef.current = false;
      return;
    }
    const animated = !isInitialLoadRef.current;
    scheduleStickToBottom(animated);

    if (isInitialLoadRef.current && messages.length > 0) {
      isInitialLoadRef.current = false;
    }
  }, [messages.length, scheduleStickToBottom]);

  useEffect(() => {
    isInitialLoadRef.current = true;
  }, [conversationId]);

  return { isInitialLoadRef, suppressAutoScrollRef };
}
