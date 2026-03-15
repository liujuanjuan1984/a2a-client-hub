import { useCallback, useRef, useState, useEffect } from "react";
import {
  FlatList,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
} from "react-native";

import { type ChatMessage } from "@/lib/api/chat-utils";
import {
  getAnchoredOffsetAfterContentResize,
  shouldShowScrollToBottom,
  shouldStickToBottom,
} from "@/lib/chatScroll";

const SEND_SCROLL_SETTLE_MS = Platform.OS === "ios" ? 120 : 60;
const HISTORY_AUTOLOAD_THRESHOLD = 72;

export function useChatScroll(
  streamState: string | undefined,
  onLoadEarlier?: () => Promise<void> | void,
) {
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const scrollOffsetRef = useRef(0);
  const contentHeightRef = useRef(0);
  const prependAnchorRef = useRef<{
    offset: number;
    contentHeight: number;
  } | null>(null);
  const contentSizeAnchorRef = useRef<{
    offset: number;
    contentHeight: number;
  } | null>(null);

  const shouldStickToBottomRef = useRef(true);
  const forceScrollToBottomRef = useRef(false);
  const scrollSettleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  const clearScrollSettleTimer = useCallback(() => {
    if (scrollSettleTimerRef.current) {
      clearTimeout(scrollSettleTimerRef.current);
      scrollSettleTimerRef.current = null;
    }
  }, []);

  const scrollToBottom = useCallback((animated: boolean) => {
    listRef.current?.scrollToEnd({ animated });
  }, []);

  const scheduleScrollSettleTimer = useCallback(() => {
    try {
      scrollSettleTimerRef.current = setTimeout(() => {
        scrollToBottom(false);
        forceScrollToBottomRef.current = false;
      }, SEND_SCROLL_SETTLE_MS);
    } catch {
      scrollSettleTimerRef.current = null;
      scrollToBottom(false);
      forceScrollToBottomRef.current = false;
    }
  }, [scrollToBottom]);

  const scheduleStickToBottom = useCallback(
    (animated: boolean) => {
      if (!shouldStickToBottomRef.current && !forceScrollToBottomRef.current) {
        return;
      }
      requestAnimationFrame(() => {
        scrollToBottom(animated);
      });
      clearScrollSettleTimer();
      scheduleScrollSettleTimer();
    },
    [clearScrollSettleTimer, scheduleScrollSettleTimer, scrollToBottom],
  );

  useEffect(() => () => clearScrollSettleTimer(), [clearScrollSettleTimer]);

  const handleListContentSizeChange = useCallback(
    (_w: number, h: number) => {
      const anchor = prependAnchorRef.current ?? contentSizeAnchorRef.current;
      if (anchor) {
        listRef.current?.scrollToOffset({
          offset: getAnchoredOffsetAfterContentResize(anchor, h),
          animated: false,
        });
        prependAnchorRef.current = null;
        contentSizeAnchorRef.current = null;
        contentHeightRef.current = h;
        return;
      }
      contentHeightRef.current = h;
      if (streamState === "streaming" || forceScrollToBottomRef.current) {
        scheduleStickToBottom(false);
      }
    },
    [scheduleStickToBottom, streamState],
  );

  const captureContentSizeAnchor = useCallback(() => {
    contentSizeAnchorRef.current = {
      offset: scrollOffsetRef.current,
      contentHeight: contentHeightRef.current,
    };
  }, []);

  const handleListScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const offsetY = event.nativeEvent.contentOffset?.y ?? 0;
      const viewportHeight = event.nativeEvent.layoutMeasurement?.height ?? 0;
      const contentHeight = event.nativeEvent.contentSize?.height ?? 0;
      shouldStickToBottomRef.current = shouldStickToBottom({
        offsetY,
        viewportHeight,
        contentHeight,
      });
      scrollOffsetRef.current = offsetY;

      setShowScrollToBottom(
        shouldShowScrollToBottom({ offsetY, viewportHeight, contentHeight }),
      );

      if (offsetY <= HISTORY_AUTOLOAD_THRESHOLD && onLoadEarlier) {
        prependAnchorRef.current = {
          offset: scrollOffsetRef.current,
          contentHeight: contentHeightRef.current,
        };
        const p = onLoadEarlier();
        if (p instanceof Promise) {
          p.catch(() => {
            prependAnchorRef.current = null;
          });
        }
      }
    },
    [onLoadEarlier],
  );

  return {
    listRef,
    showScrollToBottom,
    scrollToBottom,
    scheduleStickToBottom,
    forceScrollToBottomRef,
    shouldStickToBottomRef,
    props: {
      listRef,
      showScrollToBottom,
      scrollToBottom,
      onListContentSizeChange: handleListContentSizeChange,
      onListScroll: handleListScroll,
      captureContentSizeAnchor,
    },
  };
}
