import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FlatList,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
} from "react-native";

import { PAGE_TOP_OFFSET } from "@/components/layout/spacing";
import { useAppSafeArea } from "@/components/layout/useAppSafeArea";
import {
  useAgentsCatalogQuery,
  useValidateAgentMutation,
} from "@/hooks/useAgentsCatalogQuery";
import { useChatBlockDetailController } from "@/hooks/useChatBlockDetailController";
import { useChatComposerController } from "@/hooks/useChatComposerController";
import { useSessionHistoryQuery } from "@/hooks/useChatHistoryQuery";
import { useChatInterruptController } from "@/hooks/useChatInterruptController";
import {
  type GenericCapabilityStatus,
  useExtensionCapabilitiesQuery,
} from "@/hooks/useExtensionCapabilitiesQuery";
import { useRefreshOnFocus } from "@/hooks/useRefreshOnFocus";
import { invokeAgent } from "@/lib/api/a2aAgents";
import {
  A2AExtensionCallError,
  commandSession,
  recoverInterrupts,
} from "@/lib/api/a2aExtensions";
import type { ChatMessage } from "@/lib/api/chat-utils";
import { invokeHubAgent } from "@/lib/api/hubA2aAgentsUser";
import { continueSession } from "@/lib/api/sessions";
import {
  buildInvokePayload,
  getPendingInterrupt,
  getPendingInterruptQueue,
  getSharedModelSelection,
} from "@/lib/chat-utils";
import { addConversationOverlayMessage } from "@/lib/chatHistoryCache";
import {
  getAnchoredOffsetAfterContentResize,
  shouldShowScrollToBottom,
  shouldStickToBottom,
} from "@/lib/chatScroll";
import { blurActiveElement } from "@/lib/focus";
import { generateUuid } from "@/lib/id";
import { getInvokeMetadataBindings } from "@/lib/invokeMetadata";
import {
  getOpencodeDirectory,
  pickOpencodeDirectoryMetadata,
} from "@/lib/opencodeMetadata";
import { buildChatRoute } from "@/lib/routes";
import { buildContinueBindingPayload } from "@/lib/sessionBinding";
import { parseComposerInput } from "@/lib/sessionCommand";
import { mapA2AMessageToChatMessage } from "@/lib/sessionHistory";
import { readSharedSessionBinding } from "@/lib/sharedMetadata";
import { toast } from "@/lib/toast";
import { type AgentSource, useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";

const HISTORY_AUTOLOAD_THRESHOLD = 72;
const SEND_SCROLL_SETTLE_MS = Platform.OS === "ios" ? 120 : 60;
const INTERRUPT_RECOVERY_THROTTLE_MS = 5_000;
const PREEMPT_FEEDBACK_THROTTLE_MS = 2_500;

export function useChatScreenController({
  routeAgentId,
  conversationId,
}: {
  routeAgentId?: string | null;
  conversationId?: string;
}) {
  const router = useRouter();
  const insets = useAppSafeArea();
  const storeActiveAgentId = useAgentStore((state) => state.activeAgentId);
  const activeAgentId = routeAgentId || storeActiveAgentId;

  const { data: agents = [], isFetched: hasFetchedAgents } =
    useAgentsCatalogQuery(true);
  const validateAgentMutation = useValidateAgentMutation();

  const agent = useMemo(
    () => agents.find((item) => item.id === activeAgentId),
    [agents, activeAgentId],
  );
  const ensureSession = useChatStore((state) => state.ensureSession);
  const sendMessage = useChatStore((state) => state.sendMessage);
  const retryMessage = useChatStore((state) => state.retryMessage);
  const resumeMessage = useChatStore((state) => state.resumeMessage);
  const cancelMessage = useChatStore((state) => state.cancelMessage);
  const clearPendingInterrupt = useChatStore(
    (state) => state.clearPendingInterrupt,
  );
  const replaceRecoveredInterrupts = useChatStore(
    (state) => state.replaceRecoveredInterrupts,
  );
  const setOpencodeDirectory = useChatStore(
    (state) => state.setOpencodeDirectory,
  );
  const setInvokeMetadataBindings = useChatStore(
    (state) => state.setInvokeMetadataBindings,
  );
  const setSharedModelSelection = useChatStore(
    (state) => state.setSharedModelSelection,
  );
  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );

  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [showSessionPicker, setShowSessionPicker] = useState(false);
  const [showInvokeMetadataModal, setShowInvokeMetadataModal] = useState(false);
  const [showCodexDiscovery, setShowCodexDiscovery] = useState(false);
  const suppressAutoScrollRef = useRef(false);
  const shouldStickToBottomRef = useRef(true);
  const forceScrollToBottomRef = useRef(false);
  const lastPreemptFeedbackRef = useRef<{
    conversationId: string;
    shownAt: number;
  } | null>(null);
  const scrollSettleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  const listRef = useRef<FlatList<ChatMessage>>(null);
  const scrollOffsetRef = useRef(0);
  const contentHeightRef = useRef(0);
  const prependAnchorRef = useRef<{
    offset: number;
    contentHeight: number;
  } | null>(null);
  const contentSizeAnchorRef = useRef<{
    offset: number;
    contentHeight: number;
  } | null>(null);
  const lastInterruptRecoveryRef = useRef<{
    key: string;
    triggeredAt: number;
  } | null>(null);
  const loadingEarlierRef = useRef(false);
  const isInitialLoadRef = useRef(true);
  const historyPaused = session?.streamState === "streaming";

  const sessionHistoryQuery = useSessionHistoryQuery({
    conversationId,
    enabled: Boolean(conversationId),
    paused: historyPaused,
  });
  const messages = sessionHistoryQuery.messages;

  useRefreshOnFocus(sessionHistoryQuery.loadFirstPage);

  const historyLoading = sessionHistoryQuery.loading;
  const historyLoadingMore = sessionHistoryQuery.loadingMore;
  const historyNextPage = sessionHistoryQuery.nextPage;
  const historyError =
    sessionHistoryQuery.error instanceof Error
      ? sessionHistoryQuery.error.message
      : null;
  const sessionSource = session?.source ?? null;
  const pendingInterrupts = getPendingInterruptQueue(session);
  const pendingInterrupt = getPendingInterrupt(session);
  const pendingInterruptCount = pendingInterrupts.length;
  const lastResolvedInterrupt = session?.lastResolvedInterrupt ?? null;
  const boundExternalSessionId =
    session?.externalSessionRef?.externalSessionId?.trim() ?? "";
  const selectedModel = getSharedModelSelection(session?.metadata);
  const opencodeDirectory = getOpencodeDirectory(session?.metadata);
  const invokeMetadataBindings = getInvokeMetadataBindings(session?.metadata);
  const extensionCapabilitiesQuery = useExtensionCapabilitiesQuery({
    agentId: activeAgentId,
    source: agent?.source,
  });
  const runtimeStatusContract =
    extensionCapabilitiesQuery.runtimeStatusContract ?? undefined;
  const modelSelectionStatus: GenericCapabilityStatus =
    !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.modelSelectionStatus;
  const providerDiscoveryStatus: GenericCapabilityStatus =
    !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.providerDiscoveryStatus;
  const interruptRecoveryStatus: GenericCapabilityStatus =
    !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.interruptRecoveryStatus;
  const sessionCommandStatus: GenericCapabilityStatus =
    !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.sessionCommandStatus;
  const sessionPromptAsyncStatus: GenericCapabilityStatus =
    !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.sessionPromptAsyncStatus;
  const invokeMetadataStatus: GenericCapabilityStatus =
    !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.invokeMetadataStatus;
  const codexDiscoveryStatus =
    !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.codexDiscoveryStatus;
  const codexDiscovery = extensionCapabilitiesQuery.codexDiscovery;
  const codexDiscoveryAvailableTabs =
    extensionCapabilitiesQuery.codexDiscoveryAvailableTabs;
  const canReadCodexPlugins = extensionCapabilitiesQuery.canReadCodexPlugins;
  const canBrowseCodexDiscovery =
    Boolean(activeAgentId && agent?.source) &&
    extensionCapabilitiesQuery.canShowCodexDiscovery;
  const latestMissingParams = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const item = messages[index];
      if (item?.missingParams?.length) {
        return item.missingParams;
      }
    }
    return null;
  }, [messages]);
  const invokeMetadataFields = useMemo(() => {
    const declaredFields =
      extensionCapabilitiesQuery.invokeMetadata?.fields ?? [];
    if (declaredFields.length > 0) {
      return declaredFields.map((field) => ({
        name: field.name,
        required: field.required,
        description: field.description ?? null,
      }));
    }
    return (latestMissingParams ?? []).map((field) => ({
      name: field.name,
      required: field.required,
      description: null,
    }));
  }, [extensionCapabilitiesQuery.invokeMetadata?.fields, latestMissingParams]);
  const hasInvokeMetadataBindings =
    Object.keys(invokeMetadataBindings).length > 0;
  const showInvokeMetadataControl =
    hasInvokeMetadataBindings || invokeMetadataFields.length > 0;
  const invokeMetadataRequiredCount = invokeMetadataFields.filter(
    (field) => field.required,
  ).length;
  const pendingQuestionCount =
    pendingInterrupt?.type === "question"
      ? (pendingInterrupt.details.questions?.length ?? 0)
      : 0;
  const clearScrollSettleTimer = useCallback(() => {
    if (scrollSettleTimerRef.current) {
      clearTimeout(scrollSettleTimerRef.current);
      scrollSettleTimerRef.current = null;
    }
  }, []);

  const scrollToBottom = useCallback((animated: boolean) => {
    listRef.current?.scrollToEnd({ animated });
  }, []);

  const scheduleScrollSettleTimer = useCallback(() => {
    try {
      scrollSettleTimerRef.current = setTimeout(() => {
        scrollToBottom(false);
        forceScrollToBottomRef.current = false;
      }, SEND_SCROLL_SETTLE_MS);
    } catch {
      scrollSettleTimerRef.current = null;
      scrollToBottom(false);
      forceScrollToBottomRef.current = false;
    }
  }, [scrollToBottom]);

  const scheduleStickToBottom = useCallback(
    (animated: boolean) => {
      if (!shouldStickToBottomRef.current && !forceScrollToBottomRef.current) {
        return;
      }
      requestAnimationFrame(() => {
        scrollToBottom(animated);
      });
      clearScrollSettleTimer();
      scheduleScrollSettleTimer();
    },
    [clearScrollSettleTimer, scheduleScrollSettleTimer, scrollToBottom],
  );

  const handleSendScrollIntent = useCallback(() => {
    forceScrollToBottomRef.current = true;
    shouldStickToBottomRef.current = true;
    scheduleStickToBottom(true);
  }, [scheduleStickToBottom]);

  const showPreemptFeedback = useCallback((nextConversationId: string) => {
    const lastFeedback = lastPreemptFeedbackRef.current;
    const now = Date.now();
    if (
      lastFeedback &&
      lastFeedback.conversationId === nextConversationId &&
      now - lastFeedback.shownAt < PREEMPT_FEEDBACK_THROTTLE_MS
    ) {
      return;
    }
    lastPreemptFeedbackRef.current = {
      conversationId: nextConversationId,
      shownAt: now,
    };
    toast.info(
      "Previous response interrupted",
      "Interrupted the current response and started a new turn.",
    );
  }, []);

  const appendMessageToRunningSession = useCallback(
    async (
      nextConversationId: string,
      nextAgentId: string,
      content: string,
      nextAgentSource: AgentSource,
    ) => {
      const parsedInput = parseComposerInput(content);
      if (parsedInput.kind !== "message") {
        throw new Error("Append only supports plain text messages.");
      }

      const currentSession =
        useChatStore.getState().sessions[nextConversationId];
      const externalSessionId =
        currentSession?.externalSessionRef?.externalSessionId?.trim() ?? "";
      if (currentSession?.streamState !== "streaming" || !externalSessionId) {
        throw new Error(
          "Append requires an active stream with a bound upstream session.",
        );
      }
      if (sessionPromptAsyncStatus !== "supported") {
        throw new Error(
          "Append is unavailable for the current stream. Use send to interrupt instead.",
        );
      }

      const trimmedContent = parsedInput.text.trim();
      const userMessageId = generateUuid();
      const response =
        nextAgentSource === "shared"
          ? await invokeHubAgent(
              nextAgentId,
              buildInvokePayload(
                trimmedContent,
                currentSession,
                nextConversationId,
                {
                  userMessageId,
                  sessionControlIntent: "append",
                },
              ),
            )
          : await invokeAgent(
              nextAgentId,
              buildInvokePayload(
                trimmedContent,
                currentSession,
                nextConversationId,
                {
                  userMessageId,
                  sessionControlIntent: "append",
                },
              ),
            );

      addConversationOverlayMessage(nextConversationId, {
        id: userMessageId,
        role: "user",
        content: trimmedContent,
        createdAt: new Date().toISOString(),
        status: "done",
      });
      useChatStore.getState().bindExternalSession(nextConversationId, {
        agentId: nextAgentId,
        externalSessionId:
          response.sessionControl?.sessionId?.trim() || externalSessionId,
      });
      toast.info("Message appended", "Sent to the running upstream session.");
    },
    [sessionPromptAsyncStatus],
  );

  const sendMessageWithCapabilities = useCallback(
    async (
      nextConversationId: string,
      nextAgentId: string,
      content: string,
      nextAgentSource: AgentSource,
    ) => {
      const parsedInput = parseComposerInput(content);
      if (parsedInput.kind === "command") {
        if (sessionCommandStatus !== "supported") {
          toast.error(
            "Command unavailable",
            "This agent does not expose session command support.",
          );
          const error = new Error("Session command is not supported.");
          (error as Error & { skipToast?: boolean }).skipToast = true;
          throw error;
        }

        const currentSession =
          useChatStore.getState().sessions[nextConversationId];
        const externalSessionId =
          currentSession?.externalSessionRef?.externalSessionId?.trim() ?? "";
        if (!externalSessionId) {
          toast.error(
            "Command unavailable",
            "This conversation is not bound to an upstream session yet.",
          );
          const error = new Error(
            "Session command requires an upstream session.",
          );
          (error as Error & { skipToast?: boolean }).skipToast = true;
          throw error;
        }

        const sessionBinding = readSharedSessionBinding(
          currentSession?.metadata,
        );
        const provider =
          currentSession?.externalSessionRef?.provider?.trim() ||
          sessionBinding.provider;
        const metadata = {
          ...(pickOpencodeDirectoryMetadata(currentSession?.metadata) ?? {}),
          ...(provider ? { provider } : {}),
          externalSessionId,
        };
        const createdAt = new Date().toISOString();
        const result = await commandSession({
          source: nextAgentSource,
          agentId: nextAgentId,
          sessionId: externalSessionId,
          request: {
            command: parsedInput.command,
            arguments: parsedInput.arguments,
            ...(parsedInput.prompt
              ? {
                  parts: [
                    {
                      type: "text",
                      text: parsedInput.prompt,
                    },
                  ],
                }
              : {}),
          },
          metadata,
        });
        addConversationOverlayMessage(nextConversationId, {
          id: generateUuid(),
          role: "user",
          content: parsedInput.prompt
            ? `${parsedInput.command}${
                parsedInput.arguments ? ` ${parsedInput.arguments}` : ""
              }\n${parsedInput.prompt}`
            : `${parsedInput.command}${
                parsedInput.arguments ? ` ${parsedInput.arguments}` : ""
              }`,
          createdAt,
          status: "done",
        });
        const mapped = mapA2AMessageToChatMessage(result.item, {
          fallbackCreatedAt: createdAt,
        });
        if (!mapped) {
          throw new Error(
            "Session command response did not include a usable message.",
          );
        }
        addConversationOverlayMessage(nextConversationId, mapped);
        toast.success("Command executed", parsedInput.command);
        return;
      }

      const effectiveContent = parsedInput.text;
      const currentSession =
        useChatStore.getState().sessions[nextConversationId];
      const isActivelyStreaming = currentSession?.streamState === "streaming";

      await sendMessage(
        nextConversationId,
        nextAgentId,
        effectiveContent,
        nextAgentSource,
        runtimeStatusContract,
      );
      if (isActivelyStreaming) {
        showPreemptFeedback(nextConversationId);
      }
    },
    [
      runtimeStatusContract,
      sendMessage,
      sessionCommandStatus,
      showPreemptFeedback,
    ],
  );

  const recoverPendingInterrupts = useCallback(
    async ({
      nextConversationId,
      nextAgentId,
      nextAgentSource,
      nextSessionId,
    }: {
      nextConversationId: string;
      nextAgentId: string;
      nextAgentSource: AgentSource;
      nextSessionId: string;
    }) => {
      if (interruptRecoveryStatus !== "supported") {
        return;
      }
      const resolvedSessionId = nextSessionId.trim();
      if (!resolvedSessionId) {
        return;
      }

      const recoveryKey = `${nextConversationId}:${resolvedSessionId}`;
      const lastRecovery = lastInterruptRecoveryRef.current;
      if (
        lastRecovery &&
        lastRecovery.key === recoveryKey &&
        Date.now() - lastRecovery.triggeredAt < INTERRUPT_RECOVERY_THROTTLE_MS
      ) {
        return;
      }
      lastInterruptRecoveryRef.current = {
        key: recoveryKey,
        triggeredAt: Date.now(),
      };

      try {
        const result = await recoverInterrupts({
          source: nextAgentSource,
          agentId: nextAgentId,
          sessionId: resolvedSessionId,
        });
        replaceRecoveredInterrupts(nextConversationId, result.items, {
          sessionId: resolvedSessionId,
        });
      } catch (error) {
        if (
          error instanceof A2AExtensionCallError &&
          error.errorCode === "not_supported"
        ) {
          return;
        }
        console.warn("[Chat] interrupt recovery failed", {
          conversationId: nextConversationId,
          agentId: nextAgentId,
          sessionId: resolvedSessionId,
          error:
            error instanceof Error
              ? error.message
              : "interrupt_recovery_failed",
        });
      }
    },
    [interruptRecoveryStatus, replaceRecoveredInterrupts],
  );

  const {
    interruptAction,
    questionAnswers,
    structuredResponseInput,
    handlePermissionReply,
    handlePermissionsReply,
    handleQuestionAnswerChange,
    handleQuestionOptionPick,
    handleQuestionReply,
    handleQuestionReject,
    handleStructuredResponseChange,
    handleElicitationReply,
  } = useChatInterruptController({
    activeAgentId,
    agentSource: agent?.source,
    conversationId,
    pendingInterrupt,
    lastResolvedInterrupt,
    pendingQuestionCount,
    sessionMetadata: session?.metadata,
    clearPendingInterrupt,
  });

  const canAppendToRunningStream = useMemo(() => {
    if (session?.streamState !== "streaming" || pendingInterrupt) {
      return false;
    }
    const externalSessionId =
      session.externalSessionRef?.externalSessionId?.trim() ?? "";
    return (
      sessionPromptAsyncStatus === "supported" && Boolean(externalSessionId)
    );
  }, [
    pendingInterrupt,
    session?.externalSessionRef?.externalSessionId,
    session?.streamState,
    sessionPromptAsyncStatus,
  ]);

  const streamSendHint = useMemo(() => {
    if (session?.streamState !== "streaming" || pendingInterrupt) {
      return null;
    }
    if (canAppendToRunningStream) {
      return {
        tone: "append" as const,
        message:
          "Send will interrupt the current response. Use Append to continue in the running upstream session.",
      };
    }
    return {
      tone: "interrupt" as const,
      message:
        "Append is unavailable for this stream. Sending now will interrupt the current response and start a new turn.",
    };
  }, [canAppendToRunningStream, pendingInterrupt, session?.streamState]);

  const {
    inputRef,
    inputResetKey,
    inputDefaultValue,
    inputSelection,
    hasInput,
    hasSendableInput,
    maxInputChars,
    shortcutManagerInitialPrompt,
    inputHeight,
    maxInputHeight,
    showShortcutManager,
    showDirectoryPicker,
    showModelPicker,
    openShortcutManager,
    closeShortcutManager,
    openDirectoryPicker,
    closeDirectoryPicker,
    openModelPicker,
    closeModelPicker,
    handleModelSelect,
    clearModelSelection,
    handleUseShortcut,
    clearInput,
    handleInputChange,
    handleSelectionChange,
    handleContentSizeChange,
    handleKeyPress,
    handleSend,
    handleAppend,
  } = useChatComposerController({
    activeAgentId,
    conversationId,
    agentSource: agent?.source,
    pendingInterruptActive: pendingInterruptCount > 0,
    ensureSession,
    sendMessage: sendMessageWithCapabilities,
    appendMessage: canAppendToRunningStream
      ? appendMessageToRunningSession
      : undefined,
    setSharedModelSelection,
    onAfterSend: handleSendScrollIntent,
  });

  const { handleLoadBlockContent } =
    useChatBlockDetailController(conversationId);

  useEffect(() => {
    if (activeAgentId && conversationId) {
      ensureSession(conversationId, activeAgentId);
    }
  }, [activeAgentId, conversationId, ensureSession]);

  useEffect(() => {
    if (!conversationId || !activeAgentId) return;
    const boundAgentId = activeAgentId;
    const normalizedConversationId = conversationId;
    const hasHistory = messages.length > 0;
    if (sessionSource === "manual" && !hasHistory) {
      return;
    }

    let cancelled = false;
    continueSession(conversationId)
      .then((binding) => {
        if (cancelled) return;
        const resolvedConversationId = binding.conversationId.trim();
        if (resolvedConversationId !== normalizedConversationId) {
          router.replace(buildChatRoute(boundAgentId, resolvedConversationId));
          return;
        }
        const current = useChatStore.getState().sessions[conversationId];
        const hasLocalBinding =
          (typeof current?.externalSessionRef?.externalSessionId === "string" &&
            current.externalSessionRef.externalSessionId.trim()) ||
          Object.keys(current?.metadata ?? {}).length > 0;
        const hasBindingMetadata =
          (typeof binding.metadata?.externalSessionId === "string" &&
            binding.metadata.externalSessionId.trim()) ||
          (typeof binding.metadata?.provider === "string" &&
            binding.metadata.provider.trim());
        if (hasLocalBinding && !hasBindingMetadata) {
          return;
        }
        ensureSession(conversationId, boundAgentId);
        useChatStore
          .getState()
          .bindExternalSession(
            conversationId,
            buildContinueBindingPayload(boundAgentId, binding),
          );
      })
      .catch((error) => {
        if (cancelled) return;
        if (
          sessionSource === "manual" &&
          error instanceof Error &&
          error.message === "session_not_found"
        ) {
          return;
        }
        const message = error instanceof Error ? error.message : "Bind failed.";
        toast.error("Continue session failed", message);
      });

    return () => {
      cancelled = true;
    };
  }, [
    activeAgentId,
    ensureSession,
    messages.length,
    conversationId,
    router,
    sessionSource,
  ]);

  useEffect(() => {
    if (
      !conversationId ||
      !activeAgentId ||
      !agent?.source ||
      !boundExternalSessionId
    ) {
      return;
    }
    if (interruptRecoveryStatus !== "supported") {
      return;
    }
    recoverPendingInterrupts({
      nextConversationId: conversationId,
      nextAgentId: activeAgentId,
      nextAgentSource: agent.source,
      nextSessionId: boundExternalSessionId,
    });
  }, [
    activeAgentId,
    agent?.source,
    boundExternalSessionId,
    conversationId,
    interruptRecoveryStatus,
    recoverPendingInterrupts,
  ]);

  useEffect(() => {
    if (
      session?.streamState !== "recoverable" ||
      !conversationId ||
      !activeAgentId ||
      !agent?.source ||
      !boundExternalSessionId
    ) {
      return;
    }
    recoverPendingInterrupts({
      nextConversationId: conversationId,
      nextAgentId: activeAgentId,
      nextAgentSource: agent.source,
      nextSessionId: boundExternalSessionId,
    });
  }, [
    activeAgentId,
    agent?.source,
    boundExternalSessionId,
    conversationId,
    recoverPendingInterrupts,
    session?.streamState,
  ]);

  useEffect(() => {
    if (!pendingInterrupt) {
      return;
    }
    forceScrollToBottomRef.current = true;
    shouldStickToBottomRef.current = true;
    scheduleStickToBottom(true);
  }, [pendingInterrupt?.requestId, scheduleStickToBottom]);

  const loadEarlierHistory = useCallback(async () => {
    if (!conversationId) return;
    if (historyPaused) return;
    if (typeof historyNextPage !== "number") return;
    if (historyLoadingMore) return;

    prependAnchorRef.current = {
      offset: scrollOffsetRef.current,
      contentHeight: contentHeightRef.current,
    };
    loadingEarlierRef.current = true;
    suppressAutoScrollRef.current = true;
    try {
      await sessionHistoryQuery.loadMore();
    } finally {
      loadingEarlierRef.current = false;
    }
  }, [
    historyLoadingMore,
    historyNextPage,
    historyPaused,
    sessionHistoryQuery,
    conversationId,
  ]);

  useEffect(() => {
    if (hasFetchedAgents && !agent) {
      router.replace("/");
    }
  }, [agent, hasFetchedAgents, router]);

  useFocusEffect(
    useCallback(() => {
      if (!conversationId) {
        return;
      }
      if (
        activeAgentId &&
        agent?.source &&
        boundExternalSessionId &&
        interruptRecoveryStatus === "supported"
      ) {
        recoverPendingInterrupts({
          nextConversationId: conversationId,
          nextAgentId: activeAgentId,
          nextAgentSource: agent.source,
          nextSessionId: boundExternalSessionId,
        });
      }
      forceScrollToBottomRef.current = true;
      shouldStickToBottomRef.current = true;
      scheduleStickToBottom(true);
    }, [
      activeAgentId,
      agent?.source,
      boundExternalSessionId,
      conversationId,
      interruptRecoveryStatus,
      recoverPendingInterrupts,
      scheduleStickToBottom,
    ]),
  );

  useEffect(() => {
    if (suppressAutoScrollRef.current) {
      suppressAutoScrollRef.current = false;
      return;
    }
    const animated = !isInitialLoadRef.current;
    scheduleStickToBottom(animated);

    if (isInitialLoadRef.current && messages.length > 0) {
      isInitialLoadRef.current = false;
    }
  }, [messages.length, scheduleStickToBottom]);

  useEffect(() => {
    isInitialLoadRef.current = true;
  }, [conversationId]);

  const handleListContentSizeChange = useCallback(
    (_w: number, h: number) => {
      const anchor = prependAnchorRef.current ?? contentSizeAnchorRef.current;
      if (anchor) {
        listRef.current?.scrollToOffset({
          offset: getAnchoredOffsetAfterContentResize(anchor, h),
          animated: false,
        });
        prependAnchorRef.current = null;
        contentSizeAnchorRef.current = null;
        contentHeightRef.current = h;
        return;
      }
      contentHeightRef.current = h;
      if (
        session?.streamState === "streaming" ||
        forceScrollToBottomRef.current
      ) {
        scheduleStickToBottom(false);
      }
    },
    [scheduleStickToBottom, session?.streamState],
  );

  const captureContentSizeAnchor = useCallback(() => {
    contentSizeAnchorRef.current = {
      offset: scrollOffsetRef.current,
      contentHeight: contentHeightRef.current,
    };
  }, []);

  const handleListScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const offsetY = event.nativeEvent.contentOffset?.y ?? 0;
      const viewportHeight = event.nativeEvent.layoutMeasurement?.height ?? 0;
      const contentHeight = event.nativeEvent.contentSize?.height ?? 0;
      shouldStickToBottomRef.current = shouldStickToBottom({
        offsetY,
        viewportHeight,
        contentHeight,
      });
      scrollOffsetRef.current = offsetY;

      setShowScrollToBottom(
        shouldShowScrollToBottom({ offsetY, viewportHeight, contentHeight }),
      );

      if (
        offsetY <= HISTORY_AUTOLOAD_THRESHOLD &&
        typeof historyNextPage === "number" &&
        !historyLoadingMore &&
        !historyPaused &&
        !loadingEarlierRef.current
      ) {
        loadEarlierHistory().catch(() => undefined);
      }
    },
    [historyLoadingMore, historyNextPage, historyPaused, loadEarlierHistory],
  );

  const handleTest = useCallback(async () => {
    if (!activeAgentId || !agent) return;
    blurActiveElement();
    try {
      await validateAgentMutation.mutateAsync(activeAgentId);
      toast.success("Connection OK", `${agent.name} is online.`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Connection failed.";
      toast.error("Test failed", message);
    }
  }, [activeAgentId, agent, validateAgentMutation]);

  useEffect(() => () => clearScrollSettleTimer(), [clearScrollSettleTimer]);

  const openSessionPicker = useCallback(() => {
    setShowSessionPicker(true);
  }, []);

  const closeSessionPicker = useCallback(() => {
    setShowSessionPicker(false);
  }, []);

  const handleSaveOpencodeDirectory = useCallback(
    (directory: string) => {
      if (!conversationId || !activeAgentId) {
        return;
      }
      ensureSession(conversationId, activeAgentId);
      setOpencodeDirectory(conversationId, activeAgentId, directory);
      toast.success("Working directory updated", directory);
    },
    [activeAgentId, conversationId, ensureSession, setOpencodeDirectory],
  );

  const handleClearOpencodeDirectory = useCallback(() => {
    if (!conversationId || !activeAgentId) {
      return;
    }
    ensureSession(conversationId, activeAgentId);
    setOpencodeDirectory(conversationId, activeAgentId, null);
    toast.success("Working directory cleared", "Using upstream default.");
  }, [activeAgentId, conversationId, ensureSession, setOpencodeDirectory]);

  const openInvokeMetadataModal = useCallback(() => {
    setShowInvokeMetadataModal(true);
  }, []);

  const closeInvokeMetadataModal = useCallback(() => {
    setShowInvokeMetadataModal(false);
  }, []);

  const openCodexDiscovery = useCallback(() => {
    if (!canBrowseCodexDiscovery) {
      return;
    }
    setShowCodexDiscovery(true);
  }, [canBrowseCodexDiscovery]);

  const closeCodexDiscovery = useCallback(() => {
    setShowCodexDiscovery(false);
  }, []);

  const handleSaveInvokeMetadata = useCallback(
    (bindings: Record<string, string>) => {
      if (!conversationId || !activeAgentId) {
        return;
      }
      ensureSession(conversationId, activeAgentId);
      setInvokeMetadataBindings(conversationId, activeAgentId, bindings);
      toast.success("Invoke metadata updated", "Session bindings saved.");
    },
    [activeAgentId, conversationId, ensureSession, setInvokeMetadataBindings],
  );

  const handleClearInvokeMetadata = useCallback(() => {
    if (!conversationId || !activeAgentId) {
      return;
    }
    ensureSession(conversationId, activeAgentId);
    setInvokeMetadataBindings(conversationId, activeAgentId, {});
    toast.success(
      "Invoke metadata cleared",
      "Using request or upstream defaults.",
    );
  }, [activeAgentId, conversationId, ensureSession, setInvokeMetadataBindings]);

  const handleRetry = useCallback(() => {
    if (
      !conversationId ||
      !activeAgentId ||
      session?.streamState === "streaming"
    ) {
      return;
    }
    const runRetry = async () => {
      try {
        if (session?.streamState === "recoverable") {
          if (typeof resumeMessage === "function") {
            await resumeMessage(conversationId, runtimeStatusContract);
          }
          return;
        }
        if (typeof retryMessage === "function") {
          await retryMessage(
            conversationId,
            activeAgentId,
            agent?.source || "personal",
            runtimeStatusContract,
          );
        }
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Unable to retry message.";
        toast.error("Retry failed", message);
      }
    };
    runRetry();
  }, [
    activeAgentId,
    agent?.source,
    conversationId,
    runtimeStatusContract,
    retryMessage,
    resumeMessage,
    session?.streamState,
  ]);

  const toggleDetails = useCallback(() => {
    setShowDetails((current) => !current);
  }, []);

  const handleInterruptStream = useCallback(() => {
    if (!conversationId) {
      return;
    }
    cancelMessage(conversationId);
  }, [cancelMessage, conversationId]);

  const handleSessionSelect = useCallback(
    (nextConversationId: string) => {
      if (!agent) {
        return;
      }
      blurActiveElement();
      router.replace(buildChatRoute(agent.id, nextConversationId));
    },
    [agent, router],
  );

  return {
    topInset: insets.top + PAGE_TOP_OFFSET,
    agent,
    activeAgentId,
    hasFetchedAgents,
    conversationId,
    session,
    sessionSource,
    modelSelectionStatus,
    providerDiscoveryStatus,
    sessionCommandStatus,
    invokeMetadataStatus,
    codexDiscoveryStatus,
    codexDiscovery,
    codexDiscoveryAvailableTabs,
    canReadCodexPlugins,
    canBrowseCodexDiscovery,
    selectedModel,
    opencodeDirectory,
    invokeMetadataBindings,
    invokeMetadataFields,
    hasInvokeMetadataBindings,
    showInvokeMetadataControl,
    invokeMetadataRequiredCount,
    messages,
    historyLoading,
    historyLoadingMore,
    historyNextPage,
    historyPaused,
    historyError,
    pendingInterrupt,
    pendingInterruptCount,
    streamSendHint,
    showAppendAction: canAppendToRunningStream,
    interruptAction,
    questionAnswers,
    structuredResponseInput,
    showDetails,
    toggleDetails,
    showScrollToBottom,
    scrollToBottom,
    showShortcutManager,
    showSessionPicker,
    showInvokeMetadataModal,
    showCodexDiscovery,
    showDirectoryPicker,
    showModelPicker,
    openShortcutManager,
    closeShortcutManager,
    openSessionPicker,
    closeSessionPicker,
    openInvokeMetadataModal,
    closeInvokeMetadataModal,
    openCodexDiscovery,
    closeCodexDiscovery,
    openDirectoryPicker,
    closeDirectoryPicker,
    openModelPicker,
    closeModelPicker,
    handleModelSelect,
    clearModelSelection,
    handleSaveOpencodeDirectory,
    handleClearOpencodeDirectory,
    handleSaveInvokeMetadata,
    handleClearInvokeMetadata,
    handleUseShortcut,
    handleSessionSelect,
    handleTest,
    testingConnection: validateAgentMutation.isPending,
    listRef,
    inputRef,
    inputResetKey,
    inputDefaultValue,
    inputSelection,
    hasInput,
    hasSendableInput,
    maxInputChars,
    shortcutManagerInitialPrompt,
    inputHeight,
    maxInputHeight,
    clearInput,
    handleInputChange,
    handleSelectionChange,
    handleContentSizeChange,
    handleKeyPress,
    handleSend,
    handleAppend,
    loadEarlierHistory,
    handleListContentSizeChange,
    handleListScroll,
    captureContentSizeAnchor,
    handleLoadBlockContent,
    handleRetry,
    handleInterruptStream,
    handlePermissionReply,
    handlePermissionsReply,
    handleQuestionAnswerChange,
    handleQuestionOptionPick,
    handleQuestionReply,
    handleQuestionReject,
    handleStructuredResponseChange,
    handleElicitationReply,
  };
}
