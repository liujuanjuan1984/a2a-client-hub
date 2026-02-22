import { create } from "zustand";
import { persist } from "zustand/middleware";

import { invokeAgent } from "@/lib/api/a2aAgents";
import {
  applyStreamBlockUpdate,
  type ChatMessage,
  extractRuntimeStatusEvent,
  extractSessionMeta,
  finalizeMessageBlocks,
  type RuntimeInterrupt,
  type StreamBlockUpdate,
  isInputRequiredRuntimeState,
  extractStreamBlockUpdate,
  projectPrimaryTextContent,
} from "@/lib/api/chat-utils";
import { ApiRequestError } from "@/lib/api/client";
import { invokeHubAgent } from "@/lib/api/hubA2aAgentsUser";
import {
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
import { queryKeys } from "@/lib/queryKeys";
import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";
import { createPersistStorage } from "@/lib/storage/mmkv";
import { chatConnectionService } from "@/services/chatConnectionService";
import { queryClient } from "@/services/queryClient";
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
  clearPendingInterrupt: (conversationId: string, requestId?: string) => void;
  getSessionsByAgentId: (agentId: string) => [string, AgentSession][];
  getLatestConversationIdByAgentId: (agentId: string) => string | undefined;
  cleanupSessions: () => void;
  generateConversationId: () => string;
  clearAll: () => void;
};

const isSamePendingInterrupt = (
  left: RuntimeInterrupt | null | undefined,
  right: RuntimeInterrupt | null | undefined,
) => {
  const lhs = left ?? null;
  const rhs = right ?? null;
  if (lhs === rhs) return true;
  if (!lhs || !rhs) return false;
  if (lhs.requestId !== rhs.requestId || lhs.type !== rhs.type) {
    return false;
  }

  if (lhs.type === "permission" && rhs.type === "permission") {
    const leftPatterns = lhs.details.patterns ?? [];
    const rightPatterns = rhs.details.patterns ?? [];
    if (lhs.details.permission !== rhs.details.permission) {
      return false;
    }
    return leftPatterns.join("|") === rightPatterns.join("|");
  }

  if (lhs.type === "question" && rhs.type === "question") {
    const leftQuestions = lhs.details.questions ?? [];
    const rightQuestions = rhs.details.questions ?? [];
    if (leftQuestions.length !== rightQuestions.length) {
      return false;
    }
    for (let index = 0; index < leftQuestions.length; index += 1) {
      const leftQuestion = leftQuestions[index];
      const rightQuestion = rightQuestions[index];
      if (!leftQuestion || !rightQuestion) {
        return false;
      }
      if (
        leftQuestion.header !== rightQuestion.header ||
        leftQuestion.question !== rightQuestion.question
      ) {
        return false;
      }
      if (leftQuestion.options.length !== rightQuestion.options.length) {
        return false;
      }
      for (
        let optionIndex = 0;
        optionIndex < leftQuestion.options.length;
        optionIndex += 1
      ) {
        const leftOption = leftQuestion.options[optionIndex];
        const rightOption = rightQuestion.options[optionIndex];
        if (!leftOption || !rightOption) {
          return false;
        }
        if (
          leftOption.label !== rightOption.label ||
          leftOption.value !== rightOption.value ||
          leftOption.description !== rightOption.description
        ) {
          return false;
        }
      }
    }
    return true;
  }

  return false;
};

const buildApiErrorMessage = (error: unknown): string => {
  if (!(error instanceof ApiRequestError)) {
    return error instanceof Error ? error.message : "Request failed.";
  }

  const codeSuffix = error.errorCode ? ` [${error.errorCode}]` : "";
  const upstreamMessage =
    error.upstreamError &&
    typeof error.upstreamError === "object" &&
    typeof error.upstreamError.message === "string"
      ? error.upstreamError.message
      : null;

  return upstreamMessage
    ? `${error.message}${codeSuffix}：${upstreamMessage}`
    : `${error.message}${codeSuffix}`;
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
              pendingInterrupt: null,
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
            pendingInterrupt: null,
          });
        };

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
          pendingInterrupt?: RuntimeInterrupt | null;
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
              meta.pendingInterrupt !== undefined &&
              !isSamePendingInterrupt(
                current.pendingInterrupt,
                meta.pendingInterrupt,
              )
            ) {
              nextPatch.pendingInterrupt = meta.pendingInterrupt;
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
            const existing = merged.get(message.id);
            const session = get().sessions[conversationId];
            const isActivelyStreaming =
              session?.streamState === "streaming";
            if (
              existing &&
              existing.status === "streaming" &&
              isActivelyStreaming
            ) {
              return;
            }
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
            queryClient.invalidateQueries({
              queryKey: queryKeys.history.chat(conversationId),
            });
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
          const hasRuntimeStatusEvent = runtimeStatusEvent !== null;
          const pendingInterrupt =
            runtimeStatusEvent &&
            isInputRequiredRuntimeState(runtimeStatusEvent.state)
              ? runtimeStatusEvent.interrupt
              : null;
          if (
            meta.contextId ||
            meta.provider !== undefined ||
            meta.externalSessionId !== undefined ||
            meta.transport ||
            meta.inputModes ||
            meta.outputModes ||
            hasRuntimeStatusEvent
          ) {
            updateSessionMeta({
              ...meta,
              ...(hasRuntimeStatusEvent
                ? { runtimeStatus, pendingInterrupt }
                : {}),
            });
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
            pendingInterrupt: null,
          });
          console.warn("[Chat Stream] error", {
            conversationId,
            source: get().sessions[conversationId]?.source ?? null,
            message: errorText,
            transport: get().sessions[conversationId]?.transport ?? "unknown",
          });
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
            const message = buildApiErrorMessage(error);
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
