import { invokeAgent, type A2AAgentInvokeRequest } from "@/lib/api/a2aAgents";
import {
  applyStreamBlockUpdate,
  buildInterruptEventBlockUpdate,
  type ChatMessage,
  extractStreamErrorDetails,
  extractRuntimeStatusEvent,
  extractSessionMeta,
  finalizeMessageBlocks,
  type PendingRuntimeInterrupt,
  type RuntimeStatusContract,
  type StreamErrorDetails,
  type StreamMissingParam,
  type RuntimeInterrupt,
  type StreamBlockUpdate,
  extractStreamBlockUpdate,
  projectPrimaryTextContent,
} from "@/lib/api/chat-utils";
import {
  ApiRequestError,
  isAuthorizationFailureError,
  isAuthFailureError,
} from "@/lib/api/client";
import { invokeHubAgent } from "@/lib/api/hubA2aAgentsUser";
import { listSessionMessagesPage } from "@/lib/api/sessions";
import {
  mergeExternalSessionRef,
  type AgentSession,
  type ResolvedRuntimeInterruptRecord,
} from "@/lib/chat-utils";
import {
  addConversationMessage,
  getConversationMessages,
  rekeyConversationMessage,
  setConversationMessages,
  updateConversationMessage,
  updateConversationMessageWithUpdater,
} from "@/lib/chatHistoryCache";
import { mergeChatMessagesByCanonicalId } from "@/lib/messageMerge";
import { queryKeys } from "@/lib/queryKeys";
import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";
import { chatConnectionService } from "@/services/chatConnectionService";
import { queryClient } from "@/services/queryClient";
import { type AgentSource } from "@/store/agents";

export type ChatRuntimeState = {
  sessions: Record<string, AgentSession>;
};

export type ChatRuntimeSetState<
  TState extends ChatRuntimeState = ChatRuntimeState,
> = (
  partial:
    | TState
    | Partial<TState>
    | ((state: TState) => TState | Partial<TState>),
  replace?: boolean,
) => void;

const isSamePendingInterrupt = (
  left: PendingRuntimeInterrupt | null | undefined,
  right: PendingRuntimeInterrupt | null | undefined,
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

const isSameResolvedInterrupt = (
  left: ResolvedRuntimeInterruptRecord | null | undefined,
  right: ResolvedRuntimeInterruptRecord | null | undefined,
) => {
  const lhs = left ?? null;
  const rhs = right ?? null;
  if (lhs === rhs) return true;
  if (!lhs || !rhs) return false;
  return (
    lhs.requestId === rhs.requestId &&
    lhs.type === rhs.type &&
    lhs.phase === rhs.phase &&
    lhs.resolution === rhs.resolution
  );
};

const buildApiErrorMessage = (error: unknown): string => {
  if (!(error instanceof ApiRequestError)) {
    return error instanceof Error ? error.message : "Request failed.";
  }

  const codeSuffix =
    error.errorCode && !error.message.includes(`[${error.errorCode}]`)
      ? ` [${error.errorCode}]`
      : "";
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

const normalizeErrorCode = (value: unknown): string | null =>
  typeof value === "string" && value.trim().length > 0 ? value.trim() : null;

const formatMissingParamLabel = (
  missingParams: StreamMissingParam[] | null | undefined,
) => {
  if (!missingParams?.length) {
    return null;
  }
  return missingParams.map((item) => item.name).join(", ");
};

const extractUpstreamErrorMessage = (
  upstreamError: Record<string, unknown> | null | undefined,
) => {
  if (!upstreamError) {
    return null;
  }
  const message = upstreamError.message;
  return typeof message === "string" && message.trim().length > 0
    ? message.trim()
    : null;
};

const buildStreamErrorMessage = ({
  errorText,
  details,
}: {
  errorText: string;
  details?: Partial<StreamErrorDetails>;
}) => {
  const missingParams = formatMissingParamLabel(details?.missingParams);
  if (missingParams) {
    return `缺少上游必需参数：${missingParams}`;
  }
  const upstreamMessage = extractUpstreamErrorMessage(details?.upstreamError);
  if (
    upstreamMessage &&
    ["Upstream streaming failed", "Stream error."].includes(errorText.trim())
  ) {
    return upstreamMessage;
  }
  return errorText;
};

const buildApiErrorDetails = (error: unknown) => ({
  message: buildApiErrorMessage(error),
  errorCode:
    error instanceof ApiRequestError
      ? normalizeErrorCode(error.errorCode)
      : null,
  source: error instanceof ApiRequestError ? error.source : null,
  jsonrpcCode: error instanceof ApiRequestError ? error.jsonrpcCode : null,
  missingParams: error instanceof ApiRequestError ? error.missingParams : null,
  upstreamError: error instanceof ApiRequestError ? error.upstreamError : null,
});

const streamWarnThrottleMs = 15_000;
const streamWarnTimestamps = new Map<string, number>();

const warnStreamOnce = (
  key: string,
  message: string,
  payload: Record<string, unknown>,
) => {
  const now = Date.now();
  const previous = streamWarnTimestamps.get(key);
  if (previous && now - previous < streamWarnThrottleMs) {
    return;
  }
  streamWarnTimestamps.set(key, now);
  console.warn(message, payload);
};

export const executeChatRuntime = async <TState extends ChatRuntimeState>(
  conversationId: string,
  agentId: string,
  agentSource: AgentSource,
  payload: A2AAgentInvokeRequest,
  initialAgentMessageId: string,
  get: () => TState,
  set: ChatRuntimeSetState<TState>,
  options?: {
    runtimeStatusContract?: RuntimeStatusContract | null;
  },
) => {
  const runtimeStatusContract = options?.runtimeStatusContract ?? null;
  const buildSessionsPatch = (
    sessions: Record<string, AgentSession>,
  ): Partial<TState> => ({ sessions }) as Partial<TState>;
  let activeAgentMessageId = initialAgentMessageId;
  const activeStreamMessageIds = new Set<string>([initialAgentMessageId]);
  const streamMessageIdMap = new Map<string, string>();
  const seenEventIds = new Set<string>();
  const nextExpectedSeqByMessageId = new Map<string, number>();
  const pendingChunksByMessageId = new Map<
    string,
    Map<number, StreamBlockUpdate>
  >();
  let terminalHandled = false;
  let hasObservedStreamEvent = false;
  let highestReceivedSequence =
    get().sessions[conversationId]?.lastReceivedSequence ?? null;

  const patchSession = (patch: Partial<AgentSession>) => {
    set((state) => {
      const current = state.sessions[conversationId];
      if (!current) return state;
      const hasChanges = Object.entries(patch).some(
        ([key, value]) => (current as Record<string, unknown>)[key] !== value,
      );
      if (!hasChanges) {
        return state;
      }
      return buildSessionsPatch({
        ...state.sessions,
        [conversationId]: {
          ...current,
          ...patch,
        },
      });
    });
  };

  const markSessionIdle = () => {
    patchSession({
      streamState: "idle",
      lastStreamError: null,
      pendingInterrupt: null,
    });
  };

  const updateSessionMeta = (meta: {
    contextId?: string | null;
    provider?: string | null;
    externalSessionId?: string | null;
    runtimeStatus?: string | null;
    runtimeInterruptEvent?: RuntimeInterrupt | null;
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
      if (meta.runtimeInterruptEvent?.phase === "asked") {
        if (
          !isSamePendingInterrupt(
            current.pendingInterrupt,
            meta.runtimeInterruptEvent,
          )
        ) {
          nextPatch.pendingInterrupt = meta.runtimeInterruptEvent;
        }
      } else if (meta.runtimeInterruptEvent?.phase === "resolved") {
        const resolvedInterrupt: ResolvedRuntimeInterruptRecord = {
          ...meta.runtimeInterruptEvent,
          observedAt: new Date().toISOString(),
        };
        if (
          !isSameResolvedInterrupt(
            current.lastResolvedInterrupt,
            resolvedInterrupt,
          )
        ) {
          nextPatch.lastResolvedInterrupt = resolvedInterrupt;
        }
        if (
          current.pendingInterrupt &&
          current.pendingInterrupt.requestId ===
            meta.runtimeInterruptEvent.requestId
        ) {
          // Only a matching resolved event should close the current action card.
          nextPatch.pendingInterrupt = null;
        }
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
      if (meta.provider !== undefined || meta.externalSessionId !== undefined) {
        const mergedExternalSessionRef = mergeExternalSessionRef(
          current.externalSessionRef,
          {
            provider: meta.provider,
            externalSessionId: meta.externalSessionId,
          },
        );
        const currentProvider = current.externalSessionRef?.provider ?? null;
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

      return buildSessionsPatch({
        ...state.sessions,
        [conversationId]: {
          ...current,
          ...nextPatch,
        },
      });
    });
  };

  const markActiveMessage = (messageId: string) => {
    activeAgentMessageId = messageId;
    activeStreamMessageIds.add(messageId);
    patchSession({
      lastAgentMessageId: messageId,
    });
  };

  const resolveExistingTargetMessageIds = () => {
    const currentMessages = getConversationMessages(conversationId);
    const existingIds = new Set(currentMessages.map((message) => message.id));
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
      updateConversationMessageWithUpdater(
        conversationId,
        messageId,
        (message) => {
          const finalizedBlocks = finalizeMessageBlocks(message.blocks) ?? [];
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

  const mergeHistoryMessagesById = (
    incoming: ChatMessage[],
    options?: { isActivelyStreaming?: boolean },
  ) => {
    const current = getConversationMessages(conversationId);
    const session = get().sessions[conversationId];
    const isActivelyStreaming =
      options?.isActivelyStreaming ?? session?.streamState === "streaming";
    const nextMessages = mergeChatMessagesByCanonicalId({
      current,
      incoming,
      isActivelyStreaming,
    });
    setConversationMessages(conversationId, nextMessages);
  };

  const hasRenderableAgentContent = (message: ChatMessage | undefined) => {
    if (!message || message.role !== "agent") {
      return false;
    }
    if (message.content.trim().length > 0) {
      return true;
    }
    return Array.isArray(message.blocks) && message.blocks.length > 0;
  };

  const backfillHistoryAfterSequenceGap = async () => {
    const recovered = new Map<string, ChatMessage>();
    const limit = 50;
    const maxPages = 6;
    let before: string | null = null;

    const collectPage = (
      items: Parameters<typeof mapSessionMessagesToChatMessages>[0],
    ) => {
      const mapped = mapSessionMessagesToChatMessages(items);
      mapped.forEach((message) => {
        recovered.set(message.id, message);
      });
    };

    for (let requestCount = 0; requestCount < maxPages; requestCount += 1) {
      const response = await listSessionMessagesPage(conversationId, {
        before,
        limit,
      });
      collectPage(response.items);
      const nextBefore =
        typeof response.pageInfo.nextBefore === "string" &&
        response.pageInfo.nextBefore.trim().length > 0
          ? response.pageInfo.nextBefore.trim()
          : null;
      if (!response.pageInfo.hasMoreBefore || !nextBefore) {
        break;
      }
      before = nextBefore;
    }

    if (recovered.size > 0) {
      mergeHistoryMessagesById(Array.from(recovered.values()));
      queryClient.invalidateQueries({
        queryKey: queryKeys.history.chat(conversationId),
      });
    }
  };

  const backfillHistoryAfterEmptyRender = async (
    targetMessageIds: string[],
  ): Promise<void> => {
    if (targetMessageIds.length === 0) {
      return;
    }
    warnStreamOnce(
      `empty-render-recovery:${conversationId}:${targetMessageIds.join(",")}`,
      "[Chat Stream] no renderable content after stream completion; fetching history fallback",
      {
        conversationId,
        targetMessageIds,
      },
    );
    try {
      const response = await listSessionMessagesPage(conversationId, {
        before: null,
        limit: 20,
      });
      const recovered = mapSessionMessagesToChatMessages(response.items, {
        keepEmptyMessages: true,
      });
      if (recovered.length > 0) {
        mergeHistoryMessagesById(recovered, { isActivelyStreaming: false });
        queryClient.invalidateQueries({
          queryKey: queryKeys.history.chat(conversationId),
        });
      }
      const mergedMessages = getConversationMessages(conversationId);
      const stillMissingRenderableContent = targetMessageIds.every((id) => {
        const message = mergedMessages.find((item) => item.id === id);
        return !hasRenderableAgentContent(message);
      });
      if (stillMissingRenderableContent) {
        warnStreamOnce(
          `empty-render-still-missing:${conversationId}:${targetMessageIds.join(",")}`,
          "[Chat Stream] history fallback completed but renderable content is still unavailable",
          {
            conversationId,
            targetMessageIds,
          },
        );
      }
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Empty-render recovery failed.";
      warnStreamOnce(
        `empty-render-recovery-failed:${conversationId}:${message}`,
        "[Chat Stream] empty-render recovery failed",
        {
          conversationId,
          targetMessageIds,
          message,
        },
      );
    }
  };

  const chunkBufferByMessageId = new Map<string, StreamBlockUpdate[]>();
  let bufferTimeout: ReturnType<typeof setTimeout> | null = null;

  const flushChunkBuffer = () => {
    if (bufferTimeout) {
      clearTimeout(bufferTimeout);
      bufferTimeout = null;
    }

    chunkBufferByMessageId.forEach((chunks, targetMessageId) => {
      if (chunks.length === 0) return;
      updateConversationMessageWithUpdater(
        conversationId,
        targetMessageId,
        (message) => {
          let nextBlocks = message.blocks?.map((block) => ({ ...block }));
          for (const chunk of chunks) {
            nextBlocks = applyStreamBlockUpdate(nextBlocks, chunk);
          }
          return {
            content: projectPrimaryTextContent(nextBlocks),
            blocks: nextBlocks,
            status: "streaming",
          };
        },
      );
    });
    chunkBufferByMessageId.clear();
  };

  const appendStreamChunk = (chunk: StreamBlockUpdate) => {
    const shouldFlushImmediatelyForNonTextPlaceholder = (
      targetMessageId: string,
    ) => {
      if (
        chunk.blockType !== "tool_call" &&
        chunk.blockType !== "reasoning" &&
        chunk.blockType !== "interrupt_event"
      ) {
        return false;
      }
      if ((chunkBufferByMessageId.get(targetMessageId)?.length ?? 0) > 1) {
        return false;
      }
      const targetMessage = getConversationMessages(conversationId).find(
        (message) => message.id === targetMessageId,
      );
      if (!targetMessage || targetMessage.role !== "agent") {
        return false;
      }
      return (targetMessage.blocks?.length ?? 0) === 0;
    };

    const resolveChunkMessageId = () => {
      const mapped = streamMessageIdMap.get(chunk.messageId);
      if (mapped) {
        markActiveMessage(mapped);
        return mapped;
      }

      const currentMessages = getConversationMessages(conversationId);
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
        // Before rekeying, ensure we flush any pending chunks for the placeholder
        flushChunkBuffer();
        rekeyConversationMessage(
          conversationId,
          placeholderId,
          chunk.messageId,
        );
        activeStreamMessageIds.delete(placeholderId);
      } else {
        addConversationMessage(conversationId, {
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
    const chunks = chunkBufferByMessageId.get(targetMessageId) ?? [];
    chunks.push(chunk);
    chunkBufferByMessageId.set(targetMessageId, chunks);

    if (shouldFlushImmediatelyForNonTextPlaceholder(targetMessageId)) {
      flushChunkBuffer();
      return;
    }

    if (!bufferTimeout) {
      bufferTimeout = setTimeout(flushChunkBuffer, 16);
    }
  };

  const queueIncomingChunk = (chunk: StreamBlockUpdate) => {
    const usesWeakEventIdentity = chunk.eventIdSource === "fallback_chunk";
    if (usesWeakEventIdentity) {
      warnStreamOnce(
        `weak-event-id:${conversationId}:${chunk.messageId}`,
        "[Chat Stream] weak event identity detected; duplicate suppression disabled",
        {
          conversationId,
          messageId: chunk.messageId,
          eventId: chunk.eventId,
          eventIdSource: chunk.eventIdSource,
          seq: chunk.seq,
          artifactId: chunk.artifactId,
        },
      );
    } else {
      if (seenEventIds.has(chunk.eventId)) {
        warnStreamOnce(
          `duplicate-event-id:${conversationId}:${chunk.messageId}:${chunk.eventId}`,
          "[Chat Stream] dropped duplicate stream chunk by event id",
          {
            conversationId,
            messageId: chunk.messageId,
            eventId: chunk.eventId,
            eventIdSource: chunk.eventIdSource,
            seq: chunk.seq,
          },
        );
        return;
      }
      seenEventIds.add(chunk.eventId);
    }

    if (chunk.seq === null) {
      appendStreamChunk(chunk);
      return;
    }
    if (
      highestReceivedSequence === null ||
      chunk.seq > highestReceivedSequence
    ) {
      highestReceivedSequence = chunk.seq;
      patchSession({
        lastReceivedSequence: chunk.seq,
      });
    }

    const currentExpected = nextExpectedSeqByMessageId.get(chunk.messageId);
    if (typeof currentExpected === "number" && chunk.seq < currentExpected) {
      return;
    }
    if (currentExpected === undefined) {
      nextExpectedSeqByMessageId.set(chunk.messageId, chunk.seq);
    }

    const pending = pendingChunksByMessageId.get(chunk.messageId) ?? new Map();
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

  const applyIncomingStreamData = (data: Record<string, unknown>): boolean => {
    const chunk = extractStreamBlockUpdate(data);
    const runtimeStatusEvent = extractRuntimeStatusEvent(
      data,
      runtimeStatusContract,
    );
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
    if (runtimeStatusEvent?.interrupt) {
      flushChunkBuffer();
      queueIncomingChunk(
        buildInterruptEventBlockUpdate({
          interrupt: runtimeStatusEvent.interrupt,
          messageId: activeAgentMessageId,
        }),
      );
    }

    const meta = extractSessionMeta(data);
    const runtimeStatus = runtimeStatusEvent?.state ?? null;
    const hasRuntimeStatusEvent = runtimeStatusEvent !== null;
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
          ? {
              runtimeStatus,
              runtimeInterruptEvent: runtimeStatusEvent.interrupt,
            }
          : {}),
      });
    }

    if (runtimeStatusEvent?.isFinal) {
      completeStreamingMessage();
      return true;
    }
    return false;
  };

  const finalizeStreamingFailure = ({
    errorText,
    details,
  }: {
    errorText: string;
    details?: Partial<StreamErrorDetails>;
  }) => {
    if (terminalHandled) {
      return;
    }
    terminalHandled = true;
    flushChunkBuffer();

    const normalizedErrorCode = normalizeErrorCode(details?.errorCode);
    const normalizedErrorMessage = buildStreamErrorMessage({
      errorText,
      details,
    });

    const currentMsg = getConversationMessages(conversationId).find(
      (m) => m.id === activeAgentMessageId,
    );

    updateConversationMessage(conversationId, activeAgentMessageId, {
      status: "error",
      content: currentMsg?.content ?? "",
      errorCode: normalizedErrorCode,
      errorMessage: normalizedErrorMessage,
      errorSource: details?.source ?? null,
      jsonrpcCode: details?.jsonrpcCode ?? null,
      missingParams: details?.missingParams ?? null,
      upstreamError: details?.upstreamError ?? null,
    });

    patchSession({
      streamState: "error",
      lastStreamError: normalizedErrorMessage,
      pendingInterrupt: null,
    });
    warnStreamOnce(
      `error:${conversationId}:${errorText}`,
      "[Chat Stream] stream error",
      {
        conversationId,
        source: get().sessions[conversationId]?.source ?? null,
        message: normalizedErrorMessage,
        errorCode: normalizedErrorCode,
        errorSource: details?.source ?? null,
        jsonrpcCode: details?.jsonrpcCode ?? null,
        missingParams: details?.missingParams ?? null,
        transport: get().sessions[conversationId]?.transport ?? "unknown",
      },
    );
  };

  const appendStreamError = (
    errorText: string,
    details?: Partial<StreamErrorDetails>,
  ) => {
    finalizeStreamingFailure({ errorText, details });
  };

  const completeStreamingMessage = () => {
    if (terminalHandled) {
      return;
    }
    terminalHandled = true;
    const targetMessageIds = resolveExistingTargetMessageIds();
    flushChunkBuffer();
    const finalizeCompletion = () => {
      closeStreamingMessages();
      markSessionIdle();
      queryClient
        .invalidateQueries({
          queryKey: queryKeys.history.chat(conversationId),
        })
        .catch(() => undefined);
    };

    const hasPendingSequenceGap = Array.from(
      pendingChunksByMessageId.values(),
    ).some((pending) => pending.size > 0);
    if (hasPendingSequenceGap) {
      finalizeCompletion();
      backfillHistoryAfterSequenceGap().catch((error) => {
        const message =
          error instanceof Error
            ? error.message
            : "Sequence-gap recovery failed.";
        patchSession({
          streamState: "recoverable",
          lastStreamError: message,
        });
        warnStreamOnce(
          `sequence-gap:${conversationId}:${message}`,
          "[Chat Stream] sequence-gap recovery failed",
          {
            conversationId,
            source: get().sessions[conversationId]?.source ?? null,
            message,
          },
        );
      });
      return;
    }

    const mergedMessages = getConversationMessages(conversationId);
    const needsEmptyRenderRecovery =
      hasObservedStreamEvent &&
      targetMessageIds.length > 0 &&
      targetMessageIds.every((id) => {
        const message = mergedMessages.find((item) => item.id === id);
        return !hasRenderableAgentContent(message);
      });
    if (needsEmptyRenderRecovery) {
      backfillHistoryAfterEmptyRender(targetMessageIds).finally(() => {
        finalizeCompletion();
      });
      return;
    }

    finalizeCompletion();
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
            const maybePayload =
              data.data && typeof data.data === "object"
                ? (data.data as Record<string, unknown>)
                : {};
            const details = extractStreamErrorDetails(maybePayload);
            if (details.errorCode === "session_not_found") {
              console.info("[Chat Stream] recoverable error received", {
                conversationId,
                errorCode: details.errorCode,
              });
              return false;
            }
            appendStreamError(details.message, details);
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
        finalizeStreamingFailure({
          errorText: message,
          details: {
            errorCode: normalizeErrorCode(response.error_code),
            source: response.source ?? null,
            jsonrpcCode: response.jsonrpc_code ?? null,
            missingParams: response.missing_params ?? null,
            upstreamError: response.upstream_error ?? null,
          },
        });
        return;
      }

      updateConversationMessage(conversationId, activeAgentMessageId, {
        content: response.content ?? "",
        status: "done",
        errorCode: null,
        errorMessage: null,
      });
      markSessionIdle();
    } catch (error) {
      const {
        message,
        errorCode,
        source,
        jsonrpcCode,
        missingParams,
        upstreamError,
      } = buildApiErrorDetails(error);
      finalizeStreamingFailure({
        errorText: message,
        details: {
          errorCode,
          source,
          jsonrpcCode,
          missingParams,
          upstreamError,
        },
      });
    }
  };

  try {
    if (chatConnectionService.isWsHealthy()) {
      if (await tryWebSocketTransport()) {
        return;
      }
    }
    if (chatConnectionService.isSseHealthy()) {
      if (await trySseTransport()) {
        return;
      }
    }
  } catch (error) {
    flushChunkBuffer();
    if (!isAuthFailureError(error) && !isAuthorizationFailureError(error)) {
      throw error;
    }
    const message = isAuthFailureError(error)
      ? "Authentication expired. Please sign in again."
      : buildApiErrorMessage(error);
    updateConversationMessage(conversationId, activeAgentMessageId, {
      content: message,
      status: "done",
    });
    patchSession({
      streamState: "error",
      lastStreamError: message,
      pendingInterrupt: null,
    });
    return;
  }

  if (hasObservedStreamEvent) {
    appendStreamError(
      "Streaming transport interrupted before completion; skip blocking replay.",
    );
    return;
  }
  await sendViaJsonFallback();
};
