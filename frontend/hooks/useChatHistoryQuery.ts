import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import {
  type ChatMessage,
  type MessageBlock,
  projectPrimaryTextContent,
} from "@/lib/api/chat-utils";
import {
  listSessionMessagesPage,
  querySessionMessageBlocks,
  type SessionMessageBlockItem,
} from "@/lib/api/sessions";
import { queryKeys } from "@/lib/queryKeys";
import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";

const buildBlockCacheKey = (conversationId: string, messageId: string) =>
  `${conversationId}:${messageId}`;

const mapBlocksForMessage = (
  messageId: string,
  createdAt: string,
  blocks: SessionMessageBlockItem[],
): MessageBlock[] =>
  [...blocks]
    .sort((left, right) => left.seq - right.seq)
    .map((block, index) => {
      const blockId =
        typeof block.id === "string" && block.id.trim()
          ? block.id
          : `${messageId}:${index + 1}`;
      return {
        id: blockId,
        type: block.type,
        content: typeof block.content === "string" ? block.content : "",
        isFinished: block.isFinished === true,
        createdAt,
        updatedAt: createdAt,
      };
    });

export function useSessionHistoryQuery(options: {
  conversationId?: string;
  enabled: boolean;
  paused?: boolean;
}) {
  const { conversationId, enabled, paused = false } = options;
  const [blocksByCacheKey, setBlocksByCacheKey] = useState<
    Record<string, SessionMessageBlockItem[]>
  >({});
  const [loadingByCacheKey, setLoadingByCacheKey] = useState<
    Record<string, boolean>
  >({});
  const cachedBlockKeysRef = useRef(new Set<string>());
  const inFlightByCacheKeyRef = useRef(new Map<string, Promise<void>>());

  useEffect(() => {
    setBlocksByCacheKey({});
    setLoadingByCacheKey({});
    cachedBlockKeysRef.current.clear();
    inFlightByCacheKeyRef.current.clear();
  }, [conversationId]);

  const fetchPage = useCallback(
    async (page: number) => {
      if (!conversationId) {
        throw new Error("Conversation id is required.");
      }
      const response = await listSessionMessagesPage(conversationId, {
        page,
        size: 100,
      });
      return {
        items: mapSessionMessagesToChatMessages(response.items, {
          keepEmptyMessages: true,
        }),
        nextPage: response.nextPage,
      };
    },
    [conversationId],
  );

  const query = usePaginatedList<ChatMessage>({
    queryKey: queryKeys.history.chat(conversationId ?? "missing"),
    fetchPage,
    getKey: (item) => item.id.trim(),
    errorTitle: "Load history failed",
    fallbackMessage: "Load failed.",
    enabled: enabled && Boolean(conversationId) && !paused,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchOnMount: true,
    staleTime: 0,
  });

  const loadMessageBlocks = useCallback(
    async (messageId: string) => {
      if (!conversationId) return;
      const resolvedMessageId =
        typeof messageId === "string" ? messageId.trim() : "";
      if (!resolvedMessageId) return;
      const cacheKey = buildBlockCacheKey(conversationId, resolvedMessageId);
      if (cachedBlockKeysRef.current.has(cacheKey)) {
        return;
      }
      const inFlight = inFlightByCacheKeyRef.current.get(cacheKey);
      if (inFlight) {
        await inFlight;
        return;
      }

      setLoadingByCacheKey((current) => ({ ...current, [cacheKey]: true }));
      const request = (async () => {
        const response = await querySessionMessageBlocks(conversationId, {
          messageIds: [resolvedMessageId],
          mode: "full",
        });
        const matched = response.items.find(
          (item) => item.messageId === resolvedMessageId,
        );
        const nextBlocks = [...(matched?.blocks ?? [])].sort(
          (left, right) => left.seq - right.seq,
        );
        cachedBlockKeysRef.current.add(cacheKey);
        setBlocksByCacheKey((current) => ({
          ...current,
          [cacheKey]: nextBlocks,
        }));
      })().finally(() => {
        inFlightByCacheKeyRef.current.delete(cacheKey);
        setLoadingByCacheKey((current) => {
          if (!current[cacheKey]) {
            return current;
          }
          const next = { ...current };
          delete next[cacheKey];
          return next;
        });
      });

      inFlightByCacheKeyRef.current.set(cacheKey, request);
      await request;
    },
    [conversationId],
  );

  const isMessageBlocksLoading = useCallback(
    (messageId: string) => {
      if (!conversationId) return false;
      const resolvedMessageId =
        typeof messageId === "string" ? messageId.trim() : "";
      if (!resolvedMessageId) return false;
      const cacheKey = buildBlockCacheKey(conversationId, resolvedMessageId);
      return loadingByCacheKey[cacheKey] === true;
    },
    [conversationId, loadingByCacheKey],
  );

  const messages = useMemo(() => {
    if (!conversationId) {
      return [];
    }
    return [...query.items]
      .map((message) => {
        const cacheKey = buildBlockCacheKey(conversationId, message.id);
        const cachedBlocks = blocksByCacheKey[cacheKey];
        if (!Array.isArray(cachedBlocks)) {
          return message;
        }
        const messageBlocks = mapBlocksForMessage(
          message.id,
          message.createdAt,
          cachedBlocks,
        );
        const blockContent = projectPrimaryTextContent(messageBlocks);
        return {
          ...message,
          blocks: messageBlocks,
          content:
            blockContent.trim().length > 0 ? blockContent : message.content,
        };
      })
      .sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  }, [blocksByCacheKey, conversationId, query.items]);

  return {
    ...query,
    messages,
    loadMessageBlocks,
    isMessageBlocksLoading,
  };
}
