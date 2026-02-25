export const CHAT_LIST_BOTTOM_STICK_THRESHOLD = 72;

export type ChatScrollMetrics = {
  offsetY: number;
  viewportHeight: number;
  contentHeight: number;
};

export type ContentSizeAnchor = {
  offset: number;
  contentHeight: number;
};

export const getDistanceToBottom = ({
  offsetY,
  viewportHeight,
  contentHeight,
}: ChatScrollMetrics): number => contentHeight - (offsetY + viewportHeight);

export const shouldStickToBottom = (
  metrics: ChatScrollMetrics,
  threshold = CHAT_LIST_BOTTOM_STICK_THRESHOLD,
): boolean => getDistanceToBottom(metrics) <= threshold;

export const shouldShowScrollToBottom = (
  metrics: ChatScrollMetrics,
  threshold?: number,
): boolean => {
  const { viewportHeight, contentHeight } = metrics;
  if (contentHeight <= viewportHeight) return false;
  const actualThreshold = threshold ?? viewportHeight;
  return getDistanceToBottom(metrics) > actualThreshold;
};

export const getAnchoredOffsetAfterContentResize = (
  anchor: ContentSizeAnchor,
  nextContentHeight: number,
): number => {
  const delta = nextContentHeight - anchor.contentHeight;
  return Math.max(0, anchor.offset + delta);
};
