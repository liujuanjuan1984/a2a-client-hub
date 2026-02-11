import { create } from "zustand";
import { persist } from "zustand/middleware";

import { type ChatMessage } from "@/lib/api/chat-utils";
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
          // Enforce 100 messages limit internally
          return {
            messages: {
              ...state.messages,
              [sessionId]: next.slice(-100),
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
    }),
    {
      name: "a2a-client-hub.messages",
      storage: createPersistStorage(),
    },
  ),
);
