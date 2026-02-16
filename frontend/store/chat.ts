import { create } from "zustand";
import { persist } from "zustand/middleware";

import { invokeAgent } from "@/lib/api/a2aAgents";
import {
  applyStreamBlockUpdate,
  type ChatMessage,
  extractRuntimeStatusEvent,
  extractSessionMeta,
  finalizeMessageBlocks,
  type StreamBlockUpdate,
  extractStreamBlockUpdate,
  projectPrimaryTextContent,
} from "@/lib/api/chat-utils";
import { invokeHubAgent } from "@/lib/api/hubA2aAgentsUser";
import {
  continueSession as continueSessionBinding,
  listSessionMessagesPage,
  type SessionMessageItem,
} from "@/lib/api/sessions";
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
import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";
import { createPersistStorage } from "@/lib/storage/mmkv";
import { chatConnectionService } from "@/services/chatConnectionService";
import { type AgentSource } from "@/store/agents";
import { useMessageStore } from "@/store/messages";

type ChatState = {
  sessions: Record<string, AgentSession>;
  ensureSession: (conversationId: string, agentId: string) => void;
  sendMessage: (
    conversationId: string,
    agentId: string,
    content: string,
    agentSource: AgentSource,
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
  getSessionsByAgentId: (agentId: string) => [string, AgentSession][];
  getLatestConversationIdByAgentId: (agentId: string) => string | undefined;
  cleanupSessions: () => void;
  generateConversationId: () => string;
  clearAll: () => void;
};

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: {},
      ensureSession: (conversationId, agentId) => {
        set((state) => {
          if (state.sessions[conversationId]) {
            return {
              sessions: {
                ...state.sessions,
                [conversationId]: {
                  ...state.sessions[conversationId],
                  lastActiveAt: new Date().toISOString(),
                },
              },
            };
          }
          return {
            sessions: {
              ...state.sessions,
              [conversationId]: createAgentSession(agentId),
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
      resetSession: (conversationId, agentId) => {
        get().cancelMessage(conversationId);
        set((state) => ({
          sessions: {
            ...state.sessions,
            [conversationId]: createAgentSession(agentId),
          },
        }));
        useMessageStore.getState().removeMessages(conversationId);
      },
      cancelMessage: (conversationId) => {
        chatConnectionService.cancelSession(conversationId);
      },
      sendMessage: async (conversationId, agentId, content, agentSource) => {
        const trimmed = content.trim();
        if (!trimmed) return;

        get().cancelMessage(conversationId);

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
          get().sessions[conversationId] ?? createAgentSession(agentId);

        set((state) => ({
          sessions: {
            ...state.sessions,
            [conversationId]: {
              ...(state.sessions[conversationId] ??
                createAgentSession(agentId)),
              lastActiveAt: new Date().toISOString(),
              streamState: "streaming",
              lastStreamError: null,
              transport: chatConnectionService.getPreferredTransport(),
            },
          },
        }));

        const messageStore = useMessageStore.getState();
        messageStore.addMessage(conversationId, userMessage);
        messageStore.addMessage(conversationId, agentMessage);

        let activeAgentMessageId = agentMessageId;
        const activeStreamMessageIds = new Set<string>([agentMessageId]);
        const streamMessageIdMap = new Map<string, string>();
        const seenEventIds = new Set<string>();
        const nextExpectedSeqByMessageId = new Map<string, number>();
        const pendingChunksByMessageId = new Map<
          string,
          Map<number, StreamBlockUpdate>
        >();
        let terminalHandled = false;
        let hasObservedStreamEvent = false;

        let rebindInFlight = false;

        const patchSession = (patch: Partial<AgentSession>) => {
          set((state) => {
            const current = state.sessions[conversationId];
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
                [conversationId]: {
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
          const current = get().sessions[conversationId];
          const shouldRebind =
            current?.externalSessionRef?.provider === "opencode";
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
            conversationId,
            source: current?.source ?? null,
            reason,
            transport: get().sessions[conversationId]?.transport ?? "unknown",
          });
          try {
            const binding = await continueSessionBinding(conversationId);
            const current =
              get().sessions[conversationId] ?? createAgentSession(agentId);
            patchSession({
              contextId: binding.contextId ?? current.contextId,
              source: binding.source ?? current.source ?? null,
              externalSessionRef: mergeExternalSessionRef(
                current.externalSessionRef,
                {
                  provider: binding.provider,
                  externalSessionId: binding.externalSessionId,
                },
              ),
              streamState: "recoverable",
              lastStreamError: reason,
            });
            console.info("[Session Rebind] success", {
              conversationId,
              source: binding.source ?? current.source ?? null,
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
              conversationId,
              source: current?.source ?? null,
              message,
            });
            return false;
          } finally {
            rebindInFlight = false;
          }
        };

        if (
          previousSession.externalSessionRef?.provider === "opencode" &&
          previousSession.streamState === "error"
        ) {
          await attemptSessionRebind(
            previousSession.lastStreamError ?? "Recover before sending",
          );
        }

        const session =
          get().sessions[conversationId] ?? createAgentSession(agentId);
        const payload = buildInvokePayload(trimmed, session, conversationId, {
          userMessageId: userMessage.id,
          clientAgentMessageId: agentMessage.id,
        });

        const updateSessionMeta = (meta: {
          contextId?: string | null;
          provider?: string | null;
          externalSessionId?: string | null;
          runtimeStatus?: string | null;
          transport?: string;
          inputModes?: string[];
          outputModes?: string[];
        }) => {
          set((state) => {
            const current = state.sessions[conversationId];
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
            if (
              meta.provider !== undefined ||
              meta.externalSessionId !== undefined
            ) {
              const mergedExternalSessionRef = mergeExternalSessionRef(
                current.externalSessionRef,
                {
                  provider: meta.provider,
                  externalSessionId: meta.externalSessionId,
                },
              );
              const currentProvider =
                current.externalSessionRef?.provider ?? null;
              const currentExternalSessionId =
                current.externalSessionRef?.externalSessionId ?? null;
              if (
                mergedExternalSessionRef.provider !== currentProvider ||
                mergedExternalSessionRef.externalSessionId !==
                  currentExternalSessionId
              ) {
                nextPatch.externalSessionRef = mergedExternalSessionRef;
              }
            }

            if (Object.keys(nextPatch).length === 0) {
              return state;
            }

            return {
              sessions: {
                ...state.sessions,
                [conversationId]: {
                  ...current,
                  ...nextPatch,
                },
              },
            };
          });
        };

        const markActiveMessage = (messageId: string) => {
          activeAgentMessageId = messageId;
          activeStreamMessageIds.add(messageId);
        };

        const resolveExistingTargetMessageIds = () => {
          const currentMessages =
            useMessageStore.getState().messages[conversationId] ?? [];
          const existingIds = new Set(
            currentMessages.map((message) => message.id),
          );
          const targets = Array.from(activeStreamMessageIds).filter((id) =>
            existingIds.has(id),
          );
          if (targets.length === 0 && existingIds.has(activeAgentMessageId)) {
            targets.push(activeAgentMessageId);
          }
          return targets;
        };

        const closeStreamingMessages = (errorText?: string) => {
          const targetMessageIds = resolveExistingTargetMessageIds();
          const now = new Date().toISOString();
          targetMessageIds.forEach((messageId) => {
            messageStore.updateMessageWithUpdater(
              conversationId,
              messageId,
              (message) => {
                const finalizedBlocks =
                  finalizeMessageBlocks(message.blocks) ?? [];
                if (!errorText) {
                  return {
                    blocks: finalizedBlocks,
                    status: "done",
                  };
                }
                return {
                  blocks: [
                    ...finalizedBlocks,
                    {
                      id: `${message.id}:error:${Date.now()}`,
                      type: "system_error",
                      content: `[Stream Error: ${errorText}]`,
                      isFinished: true,
                      createdAt: now,
                      updatedAt: now,
                    },
                  ],
                  status: "done",
                };
              },
            );
          });
          activeStreamMessageIds.clear();
        };

        const mergeHistoryMessagesById = (incoming: ChatMessage[]) => {
          const current =
            useMessageStore.getState().messages[conversationId] ?? [];
          const merged = new Map<string, ChatMessage>();
          current.forEach((message) => {
            merged.set(message.id, message);
          });
          incoming.forEach((message) => {
            merged.set(message.id, message);
          });
          const nextMessages = Array.from(merged.values()).sort((left, right) =>
            left.createdAt.localeCompare(right.createdAt),
          );
          messageStore.setMessages(conversationId, nextMessages);
        };

        const backfillHistoryAfterSequenceGap = async () => {
          const recovered = new Map<string, ChatMessage>();
          const size = 100;
          const maxPages = 20;

          const collectPage = (items: SessionMessageItem[]) => {
            const mapped = mapSessionMessagesToChatMessages(
              items,
              conversationId,
            );
            mapped.forEach((message) => {
              recovered.set(message.id, message);
            });
          };

          const firstPage = await listSessionMessagesPage(conversationId, {
            page: 1,
            size,
          });
          const pagination =
            firstPage.pagination && typeof firstPage.pagination === "object"
              ? (firstPage.pagination as Record<string, unknown>)
              : null;
          const totalPages =
            pagination && typeof pagination.pages === "number"
              ? pagination.pages
              : null;

          if (typeof totalPages === "number" && totalPages > 1) {
            const tailPageWindow = 3;
            const startPage = Math.max(1, totalPages - tailPageWindow + 1);
            for (let page = startPage; page <= totalPages; page += 1) {
              if (page === 1) {
                collectPage(firstPage.items);
                continue;
              }
              const response = await listSessionMessagesPage(conversationId, {
                page,
                size,
              });
              collectPage(response.items);
            }
          } else {
            collectPage(firstPage.items);
            let nextPage =
              typeof firstPage.nextPage === "number"
                ? firstPage.nextPage
                : undefined;
            let requestCount = 1;

            while (
              typeof nextPage === "number" &&
              requestCount < maxPages &&
              nextPage > 1
            ) {
              const response = await listSessionMessagesPage(conversationId, {
                page: nextPage,
                size,
              });
              collectPage(response.items);
              nextPage =
                typeof response.nextPage === "number"
                  ? response.nextPage
                  : undefined;
              requestCount += 1;
            }
          }

          if (recovered.size > 0) {
            mergeHistoryMessagesById(Array.from(recovered.values()));
          }
        };

        const appendStreamChunk = (chunk: StreamBlockUpdate) => {
          const resolveChunkMessageId = () => {
            const mapped = streamMessageIdMap.get(chunk.messageId);
            if (mapped) {
              markActiveMessage(mapped);
              return mapped;
            }

            const currentMessages =
              useMessageStore.getState().messages[conversationId] ?? [];
            const hasExactTarget = currentMessages.some(
              (message) => message.id === chunk.messageId,
            );
            if (hasExactTarget) {
              streamMessageIdMap.set(chunk.messageId, chunk.messageId);
              markActiveMessage(chunk.messageId);
              return chunk.messageId;
            }

            const placeholderId = activeAgentMessageId;
            const hasActivePlaceholder = currentMessages.some(
              (message) => message.id === placeholderId,
            );
            if (hasActivePlaceholder) {
              messageStore.rekeyMessage(
                conversationId,
                placeholderId,
                chunk.messageId,
              );
              activeStreamMessageIds.delete(placeholderId);
            } else {
              messageStore.addMessage(conversationId, {
                id: chunk.messageId,
                role: "agent",
                content: "",
                blocks: [],
                createdAt: new Date().toISOString(),
                status: "streaming",
              });
            }
            streamMessageIdMap.set(chunk.messageId, chunk.messageId);
            markActiveMessage(chunk.messageId);
            return chunk.messageId;
          };

          const targetMessageId = resolveChunkMessageId();
          messageStore.updateMessageWithUpdater(
            conversationId,
            targetMessageId,
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

        const queueIncomingChunk = (chunk: StreamBlockUpdate) => {
          if (seenEventIds.has(chunk.eventId)) {
            return;
          }
          seenEventIds.add(chunk.eventId);

          if (chunk.seq === null) {
            appendStreamChunk(chunk);
            return;
          }

          const currentExpected = nextExpectedSeqByMessageId.get(
            chunk.messageId,
          );
          if (
            typeof currentExpected === "number" &&
            chunk.seq < currentExpected
          ) {
            return;
          }
          if (currentExpected === undefined) {
            nextExpectedSeqByMessageId.set(chunk.messageId, chunk.seq);
          }

          const pending =
            pendingChunksByMessageId.get(chunk.messageId) ?? new Map();
          if (pending.has(chunk.seq)) {
            return;
          }
          pending.set(chunk.seq, chunk);
          pendingChunksByMessageId.set(chunk.messageId, pending);

          let nextExpected =
            nextExpectedSeqByMessageId.get(chunk.messageId) ?? chunk.seq;
          while (pending.has(nextExpected)) {
            const readyChunk = pending.get(nextExpected);
            if (!readyChunk) break;
            pending.delete(nextExpected);
            appendStreamChunk(readyChunk);
            nextExpected += 1;
          }
          nextExpectedSeqByMessageId.set(chunk.messageId, nextExpected);
          if (pending.size === 0) {
            pendingChunksByMessageId.delete(chunk.messageId);
          }
        };

        const applyIncomingStreamData = (
          data: Record<string, unknown>,
        ): boolean => {
          const chunk = extractStreamBlockUpdate(data);
          const runtimeStatusEvent = extractRuntimeStatusEvent(data);
          const kind = typeof data.kind === "string" ? data.kind : "";
          const isLegacyContentEvent =
            typeof data.content === "string" && data.content.trim().length > 0;
          if (
            chunk ||
            runtimeStatusEvent ||
            kind === "artifact-update" ||
            kind === "status-update" ||
            isLegacyContentEvent
          ) {
            hasObservedStreamEvent = true;
          }
          if (chunk) {
            queueIncomingChunk(chunk);
          }

          const meta = extractSessionMeta(data);
          const runtimeStatus = runtimeStatusEvent?.state ?? null;
          if (
            meta.contextId ||
            meta.provider !== undefined ||
            meta.externalSessionId !== undefined ||
            meta.transport ||
            meta.inputModes ||
            meta.outputModes ||
            runtimeStatus
          ) {
            updateSessionMeta({ ...meta, runtimeStatus });
          }

          if (runtimeStatusEvent?.isFinal) {
            completeStreamingMessage();
            return true;
          }
          return false;
        };

        const appendStreamError = (errorText: string) => {
          if (terminalHandled) {
            return;
          }
          terminalHandled = true;
          closeStreamingMessages(errorText);
          patchSession({
            streamState: "error",
            lastStreamError: errorText,
          });
          console.warn("[Chat Stream] error", {
            conversationId,
            source: get().sessions[conversationId]?.source ?? null,
            message: errorText,
            transport: get().sessions[conversationId]?.transport ?? "unknown",
          });
          attemptSessionRebind(errorText).catch(() => false);
        };

        const completeStreamingMessage = () => {
          if (terminalHandled) {
            return;
          }
          terminalHandled = true;
          closeStreamingMessages();
          markSessionIdle();

          if (
            Array.from(pendingChunksByMessageId.values()).some(
              (pending) => pending.size > 0,
            )
          ) {
            backfillHistoryAfterSequenceGap().catch((error) => {
              const message =
                error instanceof Error
                  ? error.message
                  : "Sequence-gap recovery failed.";
              patchSession({
                streamState: "recoverable",
                lastStreamError: message,
              });
              console.warn("[Chat Stream] sequence-gap recovery failed", {
                conversationId,
                source: get().sessions[conversationId]?.source ?? null,
                message,
              });
            });
          }
        };

        const tryWebSocketTransport = async () =>
          chatConnectionService.tryWebSocketTransport({
            conversationId,
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

                if (applyIncomingStreamData(data)) {
                  return true;
                }
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
            conversationId,
            agentId,
            source: agentSource,
            payload,
            callbacks: {
              onData: (data) => {
                return applyIncomingStreamData(data);
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
              messageStore.updateMessage(conversationId, activeAgentMessageId, {
                content: message,
                status: "done",
              });
              patchSession({
                streamState: "error",
                lastStreamError: message,
              });
              return;
            }

            messageStore.updateMessage(conversationId, activeAgentMessageId, {
              content: response.content ?? "",
              status: "done",
            });
            markSessionIdle();
          } catch (error) {
            const message =
              error instanceof Error ? error.message : "Request failed.";
            messageStore.updateMessage(conversationId, activeAgentMessageId, {
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
        if (hasObservedStreamEvent) {
          appendStreamError(
            "Streaming transport interrupted before completion; skip blocking replay.",
          );
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
      getLatestConversationIdByAgentId: (agentId) => {
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

          cleanupPlan.expiredConversationIds.forEach((conversationId) => {
            chatConnectionService.cancelSession(conversationId);
            messageStore.removeMessages(conversationId);
          });
          cleanupPlan.trimmedConversationIds.forEach((conversationId) => {
            chatConnectionService.cancelSession(conversationId);
            messageStore.removeMessages(conversationId);
          });

          cleanupPlan.orphanedMessageConversationIds.forEach(
            (conversationId) => {
              messageStore.removeMessages(conversationId);
            },
          );

          return { sessions: cleanupPlan.sessions };
        });
      },
      generateConversationId: () => generateUuid(),
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
