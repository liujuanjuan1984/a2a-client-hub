import { create } from "zustand";
import { persist } from "zustand/middleware";

import { invokeAgent } from "@/lib/api/a2aAgents";
import {
  applyStreamBlockUpdate,
  extractRuntimeStatus,
  extractSessionMeta,
  finalizeMessageBlocks,
  type StreamBlockUpdate,
  extractStreamBlockUpdate,
  projectPrimaryTextContent,
} from "@/lib/api/chat-utils";
import { invokeHubAgent } from "@/lib/api/hubA2aAgentsUser";
import { continueSession as continueSessionBinding } from "@/lib/api/sessions";
import {
  buildPersistedSessions,
  buildInvokePayload,
  buildSessionCleanupPlan,
  createAgentSession,
  mergeExternalSessionRef,
  sortSessionsByLastActive,
  type AgentSession,
} from "@/lib/chat-utils";
import { generateId, generateUuid } from "@/lib/id";
import { buildConversationSessionId, getSessionSource } from "@/lib/sessionIds";
import { createPersistStorage } from "@/lib/storage/mmkv";
import { chatConnectionService } from "@/services/chatConnectionService";
import { type AgentSource } from "@/store/agents";
import { useMessageStore } from "@/store/messages";

type ChatState = {
  sessions: Record<string, AgentSession>;
  ensureSession: (sessionId: string, agentId: string) => void;
  sendMessage: (
    sessionId: string,
    agentId: string,
    content: string,
    agentSource: AgentSource,
  ) => Promise<void>;
  cancelMessage: (sessionId: string) => void;
  resetSession: (sessionId: string, agentId: string) => void;
  bindExternalSession: (
    sessionId: string,
    payload: {
      agentId: string;
      conversationId?: string | null;
      provider?: string | null;
      externalSessionId?: string | null;
      contextId?: string | null;
      bindingMetadata?: Record<string, unknown> | null;
      metadata?: Record<string, unknown> | null;
    },
  ) => void;
  migrateSessionKey: (fromSessionId: string, toSessionId: string) => void;
  getSessionsByAgentId: (agentId: string) => [string, AgentSession][];
  getLatestSessionIdByAgentId: (agentId: string) => string | undefined;
  cleanupSessions: () => void;
  generateSessionId: () => string;
  clearAll: () => void;
};

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: {},
      ensureSession: (sessionId, agentId) => {
        set((state) => {
          if (state.sessions[sessionId]) {
            return {
              sessions: {
                ...state.sessions,
                [sessionId]: {
                  ...state.sessions[sessionId],
                  lastActiveAt: new Date().toISOString(),
                },
              },
            };
          }
          return {
            sessions: {
              ...state.sessions,
              [sessionId]: createAgentSession(agentId),
            },
          };
        });
      },
      bindExternalSession: (sessionId, payload) => {
        set((state) => ({
          sessions: {
            ...state.sessions,
            [sessionId]: {
              ...(state.sessions[sessionId] ??
                createAgentSession(payload.agentId)),
              agentId: payload.agentId,
              conversationId:
                payload.conversationId === undefined
                  ? (state.sessions[sessionId]?.conversationId ?? null)
                  : payload.conversationId,
              externalSessionRef: mergeExternalSessionRef(
                state.sessions[sessionId]?.externalSessionRef,
                payload,
              ),
              contextId:
                payload.contextId === undefined
                  ? (state.sessions[sessionId]?.contextId ?? null)
                  : payload.contextId,
              metadata: payload.metadata ?? {},
              lastActiveAt: new Date().toISOString(),
            },
          },
        }));
      },
      migrateSessionKey: (fromSessionId, toSessionId) => {
        const fromKey = fromSessionId.trim();
        const toKey = toSessionId.trim();
        if (!fromKey || !toKey || fromKey === toKey) return;

        set((state) => {
          const fromSession = state.sessions[fromKey];
          if (!fromSession && !state.sessions[toKey]) {
            return state;
          }

          const nextSessions = { ...state.sessions };
          const toSession = nextSessions[toKey];
          if (fromSession) {
            nextSessions[toKey] = {
              ...(toSession ?? {}),
              ...fromSession,
              lastActiveAt: new Date().toISOString(),
            };
            delete nextSessions[fromKey];
          }

          return {
            sessions: nextSessions,
          };
        });

        chatConnectionService.migrateSessionKey(fromKey, toKey);
        useMessageStore.getState().migrateSessionKey(fromKey, toKey);
      },
      resetSession: (sessionId, agentId) => {
        get().cancelMessage(sessionId);
        set((state) => ({
          sessions: {
            ...state.sessions,
            [sessionId]: createAgentSession(agentId),
          },
        }));
        useMessageStore.getState().removeMessages(sessionId);
      },
      cancelMessage: (sessionId) => {
        chatConnectionService.cancelSession(sessionId);
      },
      sendMessage: async (sessionId, agentId, content, agentSource) => {
        const trimmed = content.trim();
        if (!trimmed) return;

        get().cancelMessage(sessionId);

        const userMessage = {
          id: generateId(),
          role: "user" as const,
          content: trimmed,
          createdAt: new Date().toISOString(),
          status: "done" as const,
        };

        const agentMessageId = generateId();
        const agentMessage = {
          id: agentMessageId,
          role: "agent" as const,
          content: "",
          blocks: [],
          createdAt: new Date().toISOString(),
          status: "streaming" as const,
        };

        const previousSession =
          get().sessions[sessionId] ?? createAgentSession(agentId);

        set((state) => ({
          sessions: {
            ...state.sessions,
            [sessionId]: {
              ...(state.sessions[sessionId] ?? createAgentSession(agentId)),
              lastActiveAt: new Date().toISOString(),
              streamState: "streaming",
              lastStreamError: null,
              transport: chatConnectionService.getPreferredTransport(),
            },
          },
        }));

        const messageStore = useMessageStore.getState();
        messageStore.addMessage(sessionId, userMessage);
        messageStore.addMessage(sessionId, agentMessage);

        const activeAgentMessageId = agentMessageId;

        let rebindInFlight = false;

        const patchSession = (patch: Partial<AgentSession>) => {
          set((state) => {
            const current = state.sessions[sessionId];
            if (!current) return state;
            const hasChanges = Object.entries(patch).some(
              ([key, value]) =>
                (current as Record<string, unknown>)[key] !== value,
            );
            if (!hasChanges) {
              return state;
            }
            return {
              sessions: {
                ...state.sessions,
                [sessionId]: {
                  ...current,
                  ...patch,
                },
              },
            };
          });
        };

        const markSessionIdle = () => {
          patchSession({
            streamState: "idle",
            lastStreamError: null,
          });
        };

        const attemptSessionRebind = async (reason: string) => {
          const source = getSessionSource(sessionId);
          const current = get().sessions[sessionId];
          const shouldRebind =
            source === "opencode" ||
            (source === "conversation" &&
              current?.externalSessionRef?.provider === "opencode");
          if (!shouldRebind) {
            return false;
          }
          if (rebindInFlight) {
            return false;
          }
          rebindInFlight = true;
          patchSession({
            streamState: "rebinding",
            lastStreamError: reason,
          });
          console.info("[Session Rebind] start", {
            sessionId,
            source: getSessionSource(sessionId),
            reason,
            transport: get().sessions[sessionId]?.transport ?? "unknown",
          });
          try {
            const binding = await continueSessionBinding(sessionId);
            const current =
              get().sessions[sessionId] ?? createAgentSession(agentId);
            patchSession({
              conversationId: binding.conversationId ?? current.conversationId,
              contextId: binding.contextId ?? current.contextId,
              metadata: binding.metadata ?? current.metadata,
              externalSessionRef: mergeExternalSessionRef(
                current.externalSessionRef,
                {
                  provider: binding.provider,
                  externalSessionId: binding.externalSessionId,
                  contextId: binding.contextId,
                  bindingMetadata: binding.bindingMetadata,
                },
              ),
              streamState: "recoverable",
              lastStreamError: reason,
            });
            console.info("[Session Rebind] success", {
              sessionId,
              source: getSessionSource(sessionId),
              contextId: binding.contextId ?? null,
            });
            return true;
          } catch (error) {
            const message =
              error instanceof Error ? error.message : "Session rebind failed.";
            patchSession({
              streamState: "error",
              lastStreamError: message,
            });
            console.warn("[Session Rebind] failed", {
              sessionId,
              source: getSessionSource(sessionId),
              message,
            });
            return false;
          } finally {
            rebindInFlight = false;
          }
        };

        if (
          (getSessionSource(sessionId) === "opencode" ||
            (getSessionSource(sessionId) === "conversation" &&
              previousSession.externalSessionRef?.provider === "opencode")) &&
          previousSession.streamState === "error"
        ) {
          await attemptSessionRebind(
            previousSession.lastStreamError ?? "Recover before sending",
          );
        }

        const session =
          get().sessions[sessionId] ?? createAgentSession(agentId);
        const payload = buildInvokePayload(trimmed, session, sessionId);

        const updateSessionMeta = (meta: {
          contextId?: string | null;
          runtimeStatus?: string | null;
          transport?: string;
          inputModes?: string[];
          outputModes?: string[];
        }) => {
          set((state) => {
            const current = state.sessions[sessionId];
            if (!current) return state;

            const nextPatch: Partial<AgentSession> = {};
            if (
              meta.contextId !== undefined &&
              meta.contextId !== current.contextId
            ) {
              nextPatch.contextId = meta.contextId;
            }
            if (
              meta.runtimeStatus !== undefined &&
              meta.runtimeStatus !== current.runtimeStatus
            ) {
              nextPatch.runtimeStatus = meta.runtimeStatus;
            }
            if (
              meta.transport !== undefined &&
              meta.transport !== current.transport
            ) {
              nextPatch.transport = meta.transport;
            }
            if (
              meta.inputModes &&
              meta.inputModes.join("|") !== current.inputModes.join("|")
            ) {
              nextPatch.inputModes = meta.inputModes;
            }
            if (
              meta.outputModes &&
              meta.outputModes.join("|") !== current.outputModes.join("|")
            ) {
              nextPatch.outputModes = meta.outputModes;
            }

            if (Object.keys(nextPatch).length === 0) {
              return state;
            }

            return {
              sessions: {
                ...state.sessions,
                [sessionId]: {
                  ...current,
                  ...nextPatch,
                },
              },
            };
          });
        };

        const appendStreamChunk = (chunk: StreamBlockUpdate) => {
          messageStore.updateMessageWithUpdater(
            sessionId,
            activeAgentMessageId,
            (message) => {
              const nextBlocks = applyStreamBlockUpdate(message.blocks, chunk);
              return {
                content: projectPrimaryTextContent(nextBlocks),
                blocks: nextBlocks,
                status: "streaming",
              };
            },
          );
        };

        const appendStreamError = (errorText: string) => {
          messageStore.updateMessageWithUpdater(
            sessionId,
            activeAgentMessageId,
            (message) => {
              const finalizedBlocks =
                finalizeMessageBlocks(message.blocks) ?? [];
              return {
                content: `${message.content}\n[Stream Error: ${errorText}]`,
                blocks: [
                  ...finalizedBlocks,
                  {
                    id: `${message.id}:error:${Date.now()}`,
                    type: "system_error",
                    content: `[Stream Error: ${errorText}]`,
                    isFinished: true,
                    createdAt: new Date().toISOString(),
                    updatedAt: new Date().toISOString(),
                  },
                ],
                status: "done",
              };
            },
          );
          patchSession({
            streamState: "error",
            lastStreamError: errorText,
          });
          console.warn("[Chat Stream] error", {
            sessionId,
            source: getSessionSource(sessionId),
            message: errorText,
            transport: get().sessions[sessionId]?.transport ?? "unknown",
          });
          attemptSessionRebind(errorText).catch(() => false);
        };

        const applyIncomingStreamData = (data: Record<string, unknown>) => {
          const chunk = extractStreamBlockUpdate(data);
          if (chunk) {
            appendStreamChunk(chunk);
          }

          const meta = extractSessionMeta(data);
          const runtimeStatus = extractRuntimeStatus(data);
          if (
            meta.contextId ||
            meta.transport ||
            meta.inputModes ||
            meta.outputModes ||
            runtimeStatus
          ) {
            updateSessionMeta({ ...meta, runtimeStatus });
          }
        };

        const completeStreamingMessage = () => {
          messageStore.updateMessageWithUpdater(
            sessionId,
            activeAgentMessageId,
            (message) => ({
              blocks: finalizeMessageBlocks(message.blocks),
              status: "done",
            }),
          );
          markSessionIdle();
        };

        const tryWebSocketTransport = async () =>
          chatConnectionService.tryWebSocketTransport({
            sessionId,
            agentId,
            source: agentSource,
            payload,
            callbacks: {
              onData: (data) => {
                if (data.event === "error") {
                  const message =
                    typeof (data.data as { message?: unknown } | undefined)
                      ?.message === "string"
                      ? (data.data as { message: string }).message
                      : "Stream error.";
                  appendStreamError(message);
                  return true;
                }

                if (data.event === "stream_end") {
                  completeStreamingMessage();
                  return true;
                }

                applyIncomingStreamData(data);
                return false;
              },
              onDone: () => {
                completeStreamingMessage();
              },
              onStreamError: appendStreamError,
            },
          });

        const trySseTransport = async () => {
          updateSessionMeta({ transport: "http_sse" });
          return chatConnectionService.trySseTransport({
            sessionId,
            agentId,
            source: agentSource,
            payload,
            callbacks: {
              onData: (data) => {
                applyIncomingStreamData(data);
              },
              onDone: () => {
                completeStreamingMessage();
              },
              onStreamError: appendStreamError,
            },
          });
        };

        const sendViaJsonFallback = async () => {
          try {
            updateSessionMeta({ transport: "http_json" });
            const response =
              agentSource === "shared"
                ? await invokeHubAgent(agentId, payload)
                : await invokeAgent(agentId, payload);
            if (!response.success) {
              const message =
                response.error || response.error_code || "Request failed.";
              messageStore.updateMessage(sessionId, agentMessageId, {
                content: message,
                status: "done",
              });
              patchSession({
                streamState: "error",
                lastStreamError: message,
              });
              return;
            }

            messageStore.updateMessage(sessionId, agentMessageId, {
              content: response.content ?? "",
              status: "done",
            });
            markSessionIdle();
          } catch (error) {
            const message =
              error instanceof Error ? error.message : "Request failed.";
            messageStore.updateMessage(sessionId, agentMessageId, {
              content: message,
              status: "done",
            });
            patchSession({
              streamState: "error",
              lastStreamError: message,
            });
          }
        };

        if (await tryWebSocketTransport()) {
          return;
        }
        if (await trySseTransport()) {
          return;
        }
        await sendViaJsonFallback();
      },
      getSessionsByAgentId: (agentId) => {
        const sessions = Object.entries(get().sessions).filter(
          ([_, session]) => session.agentId === agentId,
        );
        return sortSessionsByLastActive(sessions);
      },
      getLatestSessionIdByAgentId: (agentId) => {
        const sessions = get().getSessionsByAgentId(agentId);
        return sessions[0]?.[0];
      },
      cleanupSessions: () => {
        set((state) => {
          const messageStore = useMessageStore.getState();
          const cleanupPlan = buildSessionCleanupPlan(
            state.sessions,
            Object.keys(messageStore.messages),
          );
          if (!cleanupPlan.changed) {
            return state;
          }

          cleanupPlan.expiredSessionIds.forEach((sessionId) => {
            chatConnectionService.cancelSession(sessionId);
            messageStore.removeMessages(sessionId);
          });
          cleanupPlan.trimmedSessionIds.forEach((sessionId) => {
            chatConnectionService.cancelSession(sessionId);
            messageStore.removeMessages(sessionId);
          });

          cleanupPlan.orphanedMessageSessionIds.forEach((sessionId) => {
            messageStore.removeMessages(sessionId);
          });

          return { sessions: cleanupPlan.sessions };
        });
      },
      generateSessionId: () => buildConversationSessionId(generateUuid()),
      clearAll: () => {
        chatConnectionService.clearAll();
        set({ sessions: {} });
      },
    }),
    {
      name: "a2a-client-hub.chat",
      storage: createPersistStorage(),
      partialize: (state) => ({
        sessions: buildPersistedSessions(state.sessions),
      }),
    },
  ),
);
