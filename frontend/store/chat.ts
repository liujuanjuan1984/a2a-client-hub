import { create } from "zustand";
import { persist } from "zustand/middleware";

import { type RuntimeStatusContract } from "@/lib/api/chat-utils";
import {
  buildPersistedSessions,
  buildInvokePayload,
  buildSessionCleanupPlan,
  createAgentSession,
  getSharedModelSelection,
  mergeExternalSessionRef,
  sortSessionsByLastActive,
  withSharedModelSelection,
  type SharedModelSelection,
  type AgentSession,
} from "@/lib/chat-utils";
import {
  addConversationMessage,
  clearAllConversationMessages,
  getConversationMessages,
  listConversationIdsWithHistory,
  removeConversationMessages,
  updateConversationMessage,
} from "@/lib/chatHistoryCache";
import { generateUuid } from "@/lib/id";
import {
  buildPersistStorageName,
  createPersistStorage,
} from "@/lib/storage/mmkv";
import { chatConnectionService } from "@/services/chatConnectionService";
import { type AgentSource } from "@/store/agents";
import { executeChatRuntime } from "@/store/chatRuntime";

const CANCEL_REQUEST_DEBOUNCE_MS = 500;
const CANCEL_REQUEST_HISTORY_TTL_MS = CANCEL_REQUEST_DEBOUNCE_MS * 4;
const recentCancelRequestAt = new Map<string, number>();
const pendingCancelRequests = new Map<string, Promise<void>>();

const pruneRecentCancelRequestAt = (now: number) => {
  recentCancelRequestAt.forEach((requestedAt, conversationId) => {
    if (now - requestedAt > CANCEL_REQUEST_HISTORY_TTL_MS) {
      recentCancelRequestAt.delete(conversationId);
    }
  });
};

const requestSessionCancel = (conversationId: string) => {
  const normalizedConversationId = conversationId.trim();
  if (!normalizedConversationId) {
    return;
  }
  if (pendingCancelRequests.has(normalizedConversationId)) {
    return;
  }
  const now = Date.now();
  pruneRecentCancelRequestAt(now);
  const previousRequestedAt = recentCancelRequestAt.get(
    normalizedConversationId,
  );
  if (
    typeof previousRequestedAt === "number" &&
    now - previousRequestedAt < CANCEL_REQUEST_DEBOUNCE_MS
  ) {
    return;
  }
  recentCancelRequestAt.set(normalizedConversationId, now);
  const cancelPromise = chatConnectionService
    .cancelSession(normalizedConversationId)
    .then((result) => {
      if (result?.status === "pending") {
        console.info("Server accepted pending cancellation for conversation", {
          conversationId: normalizedConversationId,
        });
      }
    })
    .catch(() => undefined)
    .finally(() => {
      pendingCancelRequests.delete(normalizedConversationId);
    });
  pendingCancelRequests.set(normalizedConversationId, cancelPromise);
};

type ChatState = {
  sessions: Record<string, AgentSession>;
  ensureSession: (
    conversationId: string,
    agentId: string,
    options?: {
      createdAt?: string | null;
      lastActiveAt?: string | null;
    },
  ) => void;
  sendMessage: (
    conversationId: string,
    agentId: string,
    content: string,
    agentSource: AgentSource,
    runtimeStatusContract?: RuntimeStatusContract | null,
  ) => Promise<void>;
  retryMessage: (
    conversationId: string,
    agentId: string,
    agentSource: AgentSource,
    runtimeStatusContract?: RuntimeStatusContract | null,
  ) => Promise<void>;
  resumeMessage: (
    conversationId: string,
    runtimeStatusContract?: RuntimeStatusContract | null,
  ) => Promise<void>;
  cancelMessage: (conversationId: string) => void;
  resetSession: (conversationId: string, agentId: string) => void;
  bindExternalSession: (
    conversationId: string,
    payload: {
      agentId: string;
      source?: "manual" | "scheduled" | null;
      provider?: string | null;
      externalSessionId?: string | null;
      contextId?: string | null;
    },
  ) => void;
  setSharedModelSelection: (
    conversationId: string,
    agentId: string,
    selection: SharedModelSelection | null,
  ) => void;
  clearPendingInterrupt: (conversationId: string, requestId?: string) => void;
  getLatestConversationIdByAgentId: (agentId: string) => string | undefined;
  cleanupSessions: () => void;
  generateConversationId: () => string;
  clearAll: () => void;
};

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: {},
      ensureSession: (conversationId, agentId, options) => {
        const resolvedCreatedAt =
          typeof options?.createdAt === "string" && options.createdAt.trim()
            ? options.createdAt.trim()
            : null;
        const resolvedLastActiveAt =
          typeof options?.lastActiveAt === "string" &&
          options.lastActiveAt.trim()
            ? options.lastActiveAt.trim()
            : null;
        const now = new Date().toISOString();
        set((state) => {
          if (state.sessions[conversationId]) {
            const current = state.sessions[conversationId];
            return {
              sessions: {
                ...state.sessions,
                [conversationId]: {
                  ...current,
                  createdAt:
                    resolvedCreatedAt ??
                    current.createdAt ??
                    current.lastActiveAt ??
                    now,
                  lastActiveAt: resolvedLastActiveAt ?? now,
                },
              },
            };
          }
          const nextSession = createAgentSession(agentId);
          return {
            sessions: {
              ...state.sessions,
              [conversationId]: {
                ...nextSession,
                createdAt:
                  resolvedCreatedAt ??
                  nextSession.createdAt ??
                  nextSession.lastActiveAt,
                lastActiveAt: resolvedLastActiveAt ?? nextSession.lastActiveAt,
              },
            },
          };
        });
      },
      bindExternalSession: (conversationId, payload) => {
        set((state) => ({
          sessions: {
            ...state.sessions,
            [conversationId]: {
              ...(state.sessions[conversationId] ??
                createAgentSession(payload.agentId)),
              agentId: payload.agentId,
              source:
                payload.source === undefined
                  ? (state.sessions[conversationId]?.source ?? null)
                  : payload.source,
              externalSessionRef: mergeExternalSessionRef(
                state.sessions[conversationId]?.externalSessionRef,
                payload,
              ),
              contextId:
                payload.contextId === undefined
                  ? (state.sessions[conversationId]?.contextId ?? null)
                  : payload.contextId,
              lastActiveAt: new Date().toISOString(),
            },
          },
        }));
      },
      setSharedModelSelection: (conversationId, agentId, selection) => {
        set((state) => {
          const current =
            state.sessions[conversationId] ?? createAgentSession(agentId);
          const nextMetadata = withSharedModelSelection(
            current.metadata,
            selection,
          );
          if (
            JSON.stringify(getSharedModelSelection(current.metadata)) ===
            JSON.stringify(selection)
          ) {
            return state;
          }
          return {
            sessions: {
              ...state.sessions,
              [conversationId]: {
                ...current,
                agentId,
                metadata: nextMetadata,
                lastActiveAt: new Date().toISOString(),
              },
            },
          };
        });
      },
      clearPendingInterrupt: (conversationId, requestId) => {
        set((state) => {
          const current = state.sessions[conversationId];
          if (!current?.pendingInterrupt) {
            return state;
          }
          if (requestId && current.pendingInterrupt.requestId !== requestId) {
            return state;
          }
          return {
            sessions: {
              ...state.sessions,
              [conversationId]: {
                ...current,
                pendingInterrupt: null,
              },
            },
          };
        });
      },
      resetSession: (conversationId, agentId) => {
        get().cancelMessage(conversationId);
        set((state) => ({
          sessions: {
            ...state.sessions,
            [conversationId]: createAgentSession(agentId),
          },
        }));
        removeConversationMessages(conversationId);
      },

      resumeMessage: async (conversationId, runtimeStatusContract) => {
        const state = get();
        const session = state.sessions[conversationId];
        if (!session || session.streamState !== "recoverable") {
          return;
        }

        const agentId = session.agentId;
        const agentSource = (session.source as AgentSource) ?? "shared";
        const userMessageId = session.lastUserMessageId;
        const agentMessageId = session.lastAgentMessageId;
        const resumeFromSequence = session.lastReceivedSequence;

        if (!userMessageId || !agentMessageId) {
          set((s) => ({
            sessions: {
              ...s.sessions,
              [conversationId]: {
                ...s.sessions[conversationId],
                streamState: "error",
                lastStreamError: "Cannot resume: missing message references",
              },
            },
          }));
          return;
        }

        get().cancelMessage(conversationId);

        const messages = getConversationMessages(conversationId);
        const userMessage = messages.find((m) => m.id === userMessageId);
        if (!userMessage) return;

        set((s) => ({
          sessions: {
            ...s.sessions,
            [conversationId]: {
              ...s.sessions[conversationId],
              streamState: "streaming",
              lastStreamError: null,
            },
          },
        }));

        const payload = buildInvokePayload(
          userMessage.content,
          session,
          conversationId,
          {
            userMessageId,
            agentMessageId,
            resumeFromSequence: resumeFromSequence ?? undefined,
          },
        );

        await executeChatRuntime(
          conversationId,
          agentId,
          agentSource,
          payload,
          agentMessageId,
          get,
          set,
          { runtimeStatusContract },
        );
      },
      cancelMessage: (conversationId) => {
        const normalizedConversationId = conversationId.trim();
        const current =
          get().sessions[normalizedConversationId] ??
          get().sessions[conversationId];
        const shouldCancelByState =
          current?.streamState === "streaming" ||
          current?.streamState === "recoverable";
        const shouldCancelByConnection =
          chatConnectionService.hasActiveConnection(normalizedConversationId);

        if (shouldCancelByState || shouldCancelByConnection) {
          requestSessionCancel(normalizedConversationId);
        }
        set((state) => {
          const targetConversationId = state.sessions[normalizedConversationId]
            ? normalizedConversationId
            : conversationId;
          const targetSession = state.sessions[targetConversationId];
          if (!targetSession) {
            return state;
          }
          if (
            targetSession.streamState === "idle" &&
            targetSession.pendingInterrupt == null &&
            targetSession.lastStreamError == null
          ) {
            return state;
          }
          return {
            sessions: {
              ...state.sessions,
              [targetConversationId]: {
                ...targetSession,
                streamState: "idle",
                pendingInterrupt: null,
                lastStreamError: null,
              },
            },
          };
        });
      },
      sendMessage: async (
        conversationId,
        agentId,
        content,
        agentSource,
        runtimeStatusContract,
      ) => {
        const trimmed = content.trim();
        if (!trimmed) return;

        const previousSession = get().sessions[conversationId];
        const shouldInterruptPrevious =
          previousSession?.streamState === "streaming";
        get().cancelMessage(conversationId);

        const userMessage = {
          id: generateUuid(),
          role: "user" as const,
          content: trimmed,
          createdAt: new Date().toISOString(),
          status: "done" as const,
        };

        const agentMessageId = generateUuid();
        const agentMessage = {
          id: agentMessageId,
          role: "agent" as const,
          content: "",
          blocks: [],
          createdAt: new Date().toISOString(),
          status: "streaming" as const,
        };

        set((state) => ({
          sessions: {
            ...state.sessions,
            [conversationId]: {
              ...(state.sessions[conversationId] ??
                createAgentSession(agentId)),
              lastActiveAt: new Date().toISOString(),
              streamState: "streaming",
              lastStreamError: null,
              lastUserMessageId: userMessage.id,
              lastAgentMessageId: agentMessage.id,
              lastReceivedSequence: undefined,
              transport: chatConnectionService.getPreferredTransport(),
              pendingInterrupt: null,
            },
          },
        }));

        addConversationMessage(conversationId, userMessage);
        addConversationMessage(conversationId, agentMessage);

        const session =
          get().sessions[conversationId] ?? createAgentSession(agentId);
        const payload = buildInvokePayload(trimmed, session, conversationId, {
          userMessageId: userMessage.id,
          agentMessageId: agentMessage.id,
          interrupt: shouldInterruptPrevious,
        });

        await executeChatRuntime(
          conversationId,
          agentId,
          agentSource,
          payload,
          agentMessage.id,
          get,
          set,
          { runtimeStatusContract },
        );
      },
      retryMessage: async (
        conversationId,
        agentId,
        agentSource,
        runtimeStatusContract,
      ) => {
        const session = get().sessions[conversationId];
        const userMessageId = session?.lastUserMessageId;
        const agentMessageId = session?.lastAgentMessageId;
        if (!userMessageId || !agentMessageId) {
          return;
        }
        const messages = getConversationMessages(conversationId);
        const userMessage = messages.find(
          (message) => message.id === userMessageId && message.role === "user",
        );
        if (!userMessage) {
          return;
        }

        const shouldInterruptPrevious = session?.streamState === "streaming";
        get().cancelMessage(conversationId);

        const existingAgentMessage = messages.find(
          (message) =>
            message.id === agentMessageId && message.role === "agent",
        );
        if (existingAgentMessage) {
          updateConversationMessage(conversationId, agentMessageId, {
            content: "",
            blocks: [],
            status: "streaming",
          });
        } else {
          addConversationMessage(conversationId, {
            id: agentMessageId,
            role: "agent",
            content: "",
            blocks: [],
            createdAt: new Date().toISOString(),
            status: "streaming",
          });
        }

        set((state) => ({
          sessions: {
            ...state.sessions,
            [conversationId]: {
              ...(state.sessions[conversationId] ??
                createAgentSession(agentId)),
              lastActiveAt: new Date().toISOString(),
              streamState: "streaming",
              lastStreamError: null,
              lastUserMessageId: userMessageId,
              lastAgentMessageId: agentMessageId,
              lastReceivedSequence: undefined,
              pendingInterrupt: null,
            },
          },
        }));

        const payload = buildInvokePayload(
          userMessage.content,
          get().sessions[conversationId] ?? createAgentSession(agentId),
          conversationId,
          {
            userMessageId,
            agentMessageId,
            interrupt: shouldInterruptPrevious,
          },
        );
        await executeChatRuntime(
          conversationId,
          agentId,
          agentSource,
          payload,
          agentMessageId,
          get,
          set,
          { runtimeStatusContract },
        );
      },
      getLatestConversationIdByAgentId: (agentId) => {
        const sessions = sortSessionsByLastActive(
          Object.entries(get().sessions).filter(
            ([_, session]) => session.agentId === agentId,
          ),
        );
        return sessions[0]?.[0];
      },
      cleanupSessions: () => {
        set((state) => {
          const cleanupPlan = buildSessionCleanupPlan(
            state.sessions,
            listConversationIdsWithHistory(),
          );
          if (!cleanupPlan.changed) {
            return state;
          }

          cleanupPlan.expiredConversationIds.forEach((conversationId) => {
            requestSessionCancel(conversationId);
            removeConversationMessages(conversationId);
          });
          cleanupPlan.trimmedConversationIds.forEach((conversationId) => {
            requestSessionCancel(conversationId);
            removeConversationMessages(conversationId);
          });

          cleanupPlan.orphanedMessageConversationIds.forEach(
            (conversationId) => {
              removeConversationMessages(conversationId);
            },
          );

          return { sessions: cleanupPlan.sessions };
        });
      },
      generateConversationId: () => generateUuid(),
      clearAll: () => {
        chatConnectionService.clearAll();
        clearAllConversationMessages();
        recentCancelRequestAt.clear();
        pendingCancelRequests.clear();
        set({ sessions: {} });
      },
    }),
    {
      name: buildPersistStorageName("a2a-client-hub.chat", "web_tab"),
      storage: createPersistStorage(),
      partialize: (state) => ({
        sessions: buildPersistedSessions(state.sessions),
      }),
    },
  ),
);
