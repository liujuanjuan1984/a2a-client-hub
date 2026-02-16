import { create } from "zustand";
import { persist } from "zustand/middleware";

import { type ChatMessage } from "@/lib/api/chat-utils";
import { CHAT_MESSAGE_HISTORY_LIMIT } from "@/lib/messageHistory";
import { createPersistStorage } from "@/lib/storage/mmkv";

type MessageState = {
  messages: Record<string, ChatMessage[]>;
  setMessages: (conversationId: string, messages: ChatMessage[]) => void;
  addMessage: (conversationId: string, message: ChatMessage) => void;
  updateMessage: (
    conversationId: string,
    messageId: string,
    payload: Partial<ChatMessage>,
  ) => void;
  updateMessageWithUpdater: (
    conversationId: string,
    messageId: string,
    updater: (message: ChatMessage) => Partial<ChatMessage>,
  ) => void;
  rekeyMessage: (
    conversationId: string,
    fromMessageId: string,
    toMessageId: string,
  ) => void;
  removeMessages: (conversationId: string) => void;
  pruneMessages: (conversationId: string, limit: number) => void;
  clearAll: () => void;
};

export const useMessageStore = create<MessageState>()(
  persist(
    (set) => ({
      messages: {},
      setMessages: (conversationId, messages) => {
        set((state) => ({
          messages: {
            ...state.messages,
            [conversationId]: messages,
          },
        }));
      },
      addMessage: (conversationId, message) => {
        set((state) => {
          const current = state.messages[conversationId] || [];
          const next = [...current, message];
          return {
            messages: {
              ...state.messages,
              [conversationId]: next.slice(-CHAT_MESSAGE_HISTORY_LIMIT),
            },
          };
        });
      },
      updateMessage: (conversationId, messageId, payload) => {
        set((state) => {
          const current = state.messages[conversationId] || [];
          return {
            messages: {
              ...state.messages,
              [conversationId]: current.map((m) =>
                m.id === messageId ? { ...m, ...payload } : m,
              ),
            },
          };
        });
      },
      updateMessageWithUpdater: (conversationId, messageId, updater) => {
        set((state) => {
          const current = state.messages[conversationId] || [];
          return {
            messages: {
              ...state.messages,
              [conversationId]: current.map((message) =>
                message.id === messageId
                  ? { ...message, ...updater(message) }
                  : message,
              ),
            },
          };
        });
      },
      rekeyMessage: (conversationId, fromMessageId, toMessageId) => {
        const fromId = fromMessageId.trim();
        const toId = toMessageId.trim();
        if (!fromId || !toId || fromId === toId) return;

        set((state) => {
          const current = state.messages[conversationId] || [];
          if (!current.some((message) => message.id === fromId)) {
            return state;
          }
          const remapped = current.map((message) =>
            message.id === fromId ? { ...message, id: toId } : message,
          );
          const merged = new Map<string, ChatMessage>();
          remapped.forEach((message) => {
            merged.set(message.id, message);
          });
          const next = Array.from(merged.values()).sort((left, right) =>
            left.createdAt.localeCompare(right.createdAt),
          );
          return {
            messages: {
              ...state.messages,
              [conversationId]: next,
            },
          };
        });
      },
      removeMessages: (conversationId) => {
        set((state) => {
          const next = { ...state.messages };
          delete next[conversationId];
          return { messages: next };
        });
      },
      pruneMessages: (conversationId, limit) => {
        set((state) => {
          const current = state.messages[conversationId] || [];
          if (current.length <= limit) return state;
          return {
            messages: {
              ...state.messages,
              [conversationId]: current.slice(-limit),
            },
          };
        });
      },
      clearAll: () => set({ messages: {} }),
    }),
    {
      name: "a2a-client-hub.messages",
      storage: createPersistStorage(),
    },
  ),
);
