import { create } from "zustand";
import { persist } from "zustand/middleware";

import { type ChatMessage } from "@/lib/api/chat-utils";
import { CHAT_MESSAGE_HISTORY_LIMIT } from "@/lib/messageHistory";
import { createPersistStorage } from "@/lib/storage/mmkv";

type MessageState = {
  messages: Record<string, ChatMessage[]>;
  setMessages: (sessionId: string, messages: ChatMessage[]) => void;
  addMessage: (sessionId: string, message: ChatMessage) => void;
  updateMessage: (
    sessionId: string,
    messageId: string,
    payload: Partial<ChatMessage>,
  ) => void;
  updateMessageWithUpdater: (
    sessionId: string,
    messageId: string,
    updater: (message: ChatMessage) => Partial<ChatMessage>,
  ) => void;
  removeMessages: (sessionId: string) => void;
  pruneMessages: (sessionId: string, limit: number) => void;
  migrateSessionKey: (fromSessionId: string, toSessionId: string) => void;
  clearAll: () => void;
};

export const useMessageStore = create<MessageState>()(
  persist(
    (set) => ({
      messages: {},
      setMessages: (sessionId, messages) => {
        set((state) => ({
          messages: {
            ...state.messages,
            [sessionId]: messages,
          },
        }));
      },
      addMessage: (sessionId, message) => {
        set((state) => {
          const current = state.messages[sessionId] || [];
          const next = [...current, message];
          return {
            messages: {
              ...state.messages,
              [sessionId]: next.slice(-CHAT_MESSAGE_HISTORY_LIMIT),
            },
          };
        });
      },
      updateMessage: (sessionId, messageId, payload) => {
        set((state) => {
          const current = state.messages[sessionId] || [];
          return {
            messages: {
              ...state.messages,
              [sessionId]: current.map((m) =>
                m.id === messageId ? { ...m, ...payload } : m,
              ),
            },
          };
        });
      },
      updateMessageWithUpdater: (sessionId, messageId, updater) => {
        set((state) => {
          const current = state.messages[sessionId] || [];
          return {
            messages: {
              ...state.messages,
              [sessionId]: current.map((message) =>
                message.id === messageId
                  ? { ...message, ...updater(message) }
                  : message,
              ),
            },
          };
        });
      },
      removeMessages: (sessionId) => {
        set((state) => {
          const next = { ...state.messages };
          delete next[sessionId];
          return { messages: next };
        });
      },
      pruneMessages: (sessionId, limit) => {
        set((state) => {
          const current = state.messages[sessionId] || [];
          if (current.length <= limit) return state;
          return {
            messages: {
              ...state.messages,
              [sessionId]: current.slice(-limit),
            },
          };
        });
      },
      migrateSessionKey: (fromSessionId, toSessionId) => {
        const fromKey = fromSessionId.trim();
        const toKey = toSessionId.trim();
        if (!fromKey || !toKey || fromKey === toKey) return;
        set((state) => {
          const fromItems = state.messages[fromKey] ?? [];
          if (fromItems.length === 0 && !state.messages[toKey]) {
            return state;
          }
          const toItems = state.messages[toKey] ?? [];
          const merged = new Map<string, ChatMessage>();
          [...toItems, ...fromItems].forEach((item) => {
            merged.set(item.id, item);
          });
          const nextItems = Array.from(merged.values())
            .sort((left, right) =>
              left.createdAt.localeCompare(right.createdAt),
            )
            .slice(-CHAT_MESSAGE_HISTORY_LIMIT);

          const nextMessages = { ...state.messages };
          nextMessages[toKey] = nextItems;
          delete nextMessages[fromKey];
          return { messages: nextMessages };
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
