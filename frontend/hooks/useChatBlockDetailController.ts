import { useCallback, useRef } from "react";

import { applyLoadedBlockDetail } from "@/lib/api/chat-utils";
import { querySessionMessageBlocks } from "@/lib/api/sessions";
import {
  getConversationMessages,
  updateConversationMessageWithUpdater,
} from "@/lib/chatHistoryCache";
import { toast } from "@/lib/toast";

export function useChatBlockDetailController(conversationId?: string) {
  const blockDetailInFlightRef = useRef<Set<string>>(new Set());

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
      if (latestBlock) {
        const hasContent =
          typeof latestBlock.content === "string" &&
          latestBlock.content.length > 0;
        if (latestBlock.type === "tool_call") {
          const hasStructuredToolCallDetail = Boolean(
            latestBlock.toolCallDetail,
          );
          if (
            hasStructuredToolCallDetail ||
            (!latestBlock.isFinished && hasContent)
          ) {
            return true;
          }
        } else if (hasContent) {
          return true;
        }
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
          (message) =>
            applyLoadedBlockDetail(message, {
              blockId: resolvedBlockId,
              type: blockDetail.type,
              content: blockDetail.content,
              isFinished: blockDetail.isFinished,
              toolCall: blockDetail.toolCall ?? null,
              toolCallDetail: blockDetail.toolCallDetail ?? null,
            }),
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
    handleLoadBlockContent,
  };
}
