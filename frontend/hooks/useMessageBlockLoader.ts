import { useCallback, useRef } from "react";

import { querySessionMessageBlocks } from "@/lib/api/sessions";
import {
  getConversationMessages,
  updateConversationMessageWithUpdater,
} from "@/lib/chatHistoryCache";
import { toast } from "@/lib/toast";

export function useMessageBlockLoader(conversationId: string | undefined) {
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

  return { handleLoadBlockContent };
}
