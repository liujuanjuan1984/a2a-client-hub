import { useCallback, useRef } from "react";

import { useSessionHistoryQuery } from "@/hooks/useChatHistoryQuery";
import { useRefreshOnFocus } from "@/hooks/useRefreshOnFocus";
import { querySessionMessageBlocks } from "@/lib/api/sessions";
import {
  getConversationMessages,
  updateConversationMessageWithUpdater,
} from "@/lib/chatHistoryCache";
import { toast } from "@/lib/toast";

export function useMessageState(
  conversationId: string | undefined,
  historyPaused: boolean,
) {
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

  const loadingEarlierRef = useRef(false);
  const blockDetailInFlightRef = useRef<Set<string>>(new Set());

  const loadEarlierHistory = useCallback(
    async (scrollOffset: number, contentHeight: number) => {
      if (!conversationId) return null;
      if (historyPaused) return null;
      if (typeof historyNextPage !== "number") return null;
      if (historyLoadingMore) return null;

      loadingEarlierRef.current = true;
      const anchor = {
        offset: scrollOffset,
        contentHeight,
      };

      try {
        await sessionHistoryQuery.loadMore();
        return anchor;
      } catch {
        return null;
      } finally {
        loadingEarlierRef.current = false;
      }
    },
    [
      historyLoadingMore,
      historyNextPage,
      historyPaused,
      sessionHistoryQuery,
      conversationId,
    ],
  );

  const handleLoadBlockContent = useCallback(
    async (messageId: string, blockId: string): Promise<boolean> => {
      if (!conversationId) {
        return false;
      }
      const resolvedMessageId = messageId.trim();
      const resolvedBlockId = blockId.trim();
      if (!resolvedMessageId || !resolvedBlockId) {
        return false;
      }

      const latestMessage = getConversationMessages(conversationId).find(
        (item) => item.id === resolvedMessageId,
      );
      const latestBlock = latestMessage?.blocks?.find(
        (item) => item.id === resolvedBlockId,
      );
      if (latestBlock && latestBlock.content.length > 0) {
        return true;
      }

      const inFlightKey = `${conversationId}:${resolvedBlockId}`;
      if (blockDetailInFlightRef.current.has(inFlightKey)) {
        return false;
      }
      blockDetailInFlightRef.current.add(inFlightKey);

      try {
        const response = await querySessionMessageBlocks(conversationId, {
          blockIds: [resolvedBlockId],
        });
        const blockDetail = response.items.find(
          (item) => item.id.trim() === resolvedBlockId,
        );
        if (!blockDetail) {
          toast.error("Load block failed", "Block content unavailable.");
          return false;
        }
        const detailMessageId =
          typeof blockDetail.messageId === "string"
            ? blockDetail.messageId.trim()
            : "";
        if (!detailMessageId || detailMessageId !== resolvedMessageId) {
          toast.error("Load block failed", "Block ownership mismatch.");
          return false;
        }

        updateConversationMessageWithUpdater(
          conversationId,
          resolvedMessageId,
          (message) => {
            const nextBlocks = (message.blocks ?? []).map((item) =>
              item.id === resolvedBlockId
                ? {
                    ...item,
                    type:
                      typeof blockDetail.type === "string" &&
                      blockDetail.type.trim().length > 0
                        ? blockDetail.type
                        : item.type,
                    content:
                      typeof blockDetail.content === "string"
                        ? blockDetail.content
                        : "",
                    isFinished:
                      typeof blockDetail.isFinished === "boolean"
                        ? blockDetail.isFinished
                        : item.isFinished,
                  }
                : item,
            );
            return {
              blocks: nextBlocks,
            };
          },
        );
        return true;
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Load block failed.";
        toast.error("Load block failed", message);
        return false;
      } finally {
        blockDetailInFlightRef.current.delete(inFlightKey);
      }
    },
    [conversationId],
  );

  return {
    messages,
    historyLoading,
    historyLoadingMore,
    historyNextPage,
    historyError,
    loadEarlierHistory,
    handleLoadBlockContent,
    loadingEarlierRef,
  };
}
