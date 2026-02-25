import { type InfiniteData } from "@tanstack/react-query";

import { type ChatMessage } from "@/lib/api/chat-utils";
import { queryKeys } from "@/lib/queryKeys";
import { queryClient } from "@/services/queryClient";

type ChatHistoryPage = {
  items: ChatMessage[];
  nextPage?: number;
};

const normalizeMessageId = (value: string) => value.trim();

const normalizeMessages = (items: ChatMessage[]) => {
  const ordered = [...items].sort((left, right) =>
    left.createdAt.localeCompare(right.createdAt),
  );
  const deduped = new Map<string, ChatMessage>();
  ordered.forEach((item) => {
    const id = normalizeMessageId(item.id);
    if (!id) return;
    deduped.set(id, { ...item, id });
  });
  return Array.from(deduped.values());
};

const readHistoryData = (conversationId: string) =>
  queryClient.getQueryData<InfiniteData<ChatHistoryPage, number>>(
    queryKeys.history.chat(conversationId),
  );

const flattenPages = (pages: ChatHistoryPage[]) =>
  normalizeMessages(pages.flatMap((page) => page.items ?? []));

const writeMessages = (
  conversationId: string,
  nextMessages: ChatMessage[],
  options?: { preserveNextPage?: number },
) => {
  const key = queryKeys.history.chat(conversationId);
  queryClient.setQueryData<InfiniteData<ChatHistoryPage, number>>(
    key,
    (data) => {
      const fallbackNextPage =
        options?.preserveNextPage ??
        (data && data.pages.length > 0
          ? data.pages[data.pages.length - 1]?.nextPage
          : undefined);
      return {
        pages: [
          {
            items: normalizeMessages(nextMessages),
            nextPage: fallbackNextPage,
          },
        ],
        pageParams: [1],
      };
    },
  );
};

export const getConversationMessages = (
  conversationId: string,
): ChatMessage[] => {
  const data = readHistoryData(conversationId);
  if (!data || data.pages.length === 0) {
    return [];
  }
  return flattenPages(data.pages);
};

export const setConversationMessages = (
  conversationId: string,
  messages: ChatMessage[],
) => {
  writeMessages(conversationId, messages);
};

export const addConversationMessage = (
  conversationId: string,
  message: ChatMessage,
) => {
  const current = getConversationMessages(conversationId);
  writeMessages(conversationId, [...current, message]);
};

export const updateConversationMessage = (
  conversationId: string,
  messageId: string,
  payload: Partial<ChatMessage>,
) => {
  const targetId = normalizeMessageId(messageId);
  if (!targetId) return;
  const current = getConversationMessages(conversationId);
  const next = current.map((item) =>
    item.id === targetId ? { ...item, ...payload, id: targetId } : item,
  );
  writeMessages(conversationId, next);
};

export const updateConversationMessageWithUpdater = (
  conversationId: string,
  messageId: string,
  updater: (message: ChatMessage) => Partial<ChatMessage>,
) => {
  const targetId = normalizeMessageId(messageId);
  if (!targetId) return;
  const current = getConversationMessages(conversationId);
  const next = current.map((item) =>
    item.id === targetId ? { ...item, ...updater(item), id: targetId } : item,
  );
  writeMessages(conversationId, next);
};

export const rekeyConversationMessage = (
  conversationId: string,
  fromMessageId: string,
  toMessageId: string,
) => {
  const fromId = normalizeMessageId(fromMessageId);
  const toId = normalizeMessageId(toMessageId);
  if (!fromId || !toId || fromId === toId) return;

  const current = getConversationMessages(conversationId);
  if (!current.some((item) => item.id === fromId)) {
    return;
  }
  const remapped = current.map((item) =>
    item.id === fromId ? { ...item, id: toId } : item,
  );
  writeMessages(conversationId, remapped);
};

export const removeConversationMessages = (conversationId: string) => {
  queryClient.removeQueries({
    queryKey: queryKeys.history.chat(conversationId),
    exact: true,
  });
};

export const listConversationIdsWithHistory = (): string[] => {
  const queries = queryClient
    .getQueryCache()
    .findAll({ queryKey: ["history", "chat"] });
  const ids = new Set<string>();
  queries.forEach((query) => {
    const key = query.queryKey;
    if (!Array.isArray(key) || key.length < 3) return;
    const conversationId = key[2];
    if (typeof conversationId !== "string" || !conversationId.trim()) return;
    if (conversationId === "missing") return;
    ids.add(conversationId.trim());
  });
  return Array.from(ids);
};

export const clearAllConversationMessages = () => {
  queryClient.removeQueries({
    queryKey: ["history", "chat"],
  });
};
