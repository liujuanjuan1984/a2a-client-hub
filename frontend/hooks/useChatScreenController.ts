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
import { useChatScreenHubAssistantController } from "@/hooks/useChatScreenHubAssistantController";
import { useChatScreenSessionController } from "@/hooks/useChatScreenSessionController";
import {
  type GenericCapabilityStatus,
  useExtensionCapabilitiesQuery,
} from "@/hooks/useExtensionCapabilitiesQuery";
import { useRefreshOnFocus } from "@/hooks/useRefreshOnFocus";
import {
  A2AExtensionCallError,
  recoverInterrupts,
} from "@/lib/api/a2aExtensions";
import type { ChatMessage } from "@/lib/api/chat-utils";
import { isHubAssistant } from "@/lib/api/hubAssistant";
import { continueSession } from "@/lib/api/sessions";
import {
  getPendingInterrupt,
  getPendingInterruptQueue,
  getSharedModelSelection,
} from "@/lib/chat-utils";
import {
  getAnchoredOffsetAfterContentResize,
  shouldShowScrollToBottom,
  shouldStickToBottom,
} from "@/lib/chatScroll";
import { blurActiveElement } from "@/lib/focus";
import { getInvokeMetadataBindings } from "@/lib/invokeMetadata";
import { buildChatRoute } from "@/lib/routes";
import { buildContinueBindingPayload } from "@/lib/sessionBinding";
import { toast } from "@/lib/toast";
import { type AgentSource, useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";

const HISTORY_AUTOLOAD_THRESHOLD = 72;
const SEND_SCROLL_SETTLE_MS = Platform.OS === "ios" ? 120 : 60;
const INTERRUPT_RECOVERY_THROTTLE_MS = 5_000;

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
  const isHubAssistantAgent = isHubAssistant(agent?.id);
  const ensureSession = useChatStore((state) => state.ensureSession);
  const sendMessage = useChatStore((state) => state.sendMessage);
  const retryMessage = useChatStore((state) => state.retryMessage);
  const resumeMessage = useChatStore((state) => state.resumeMessage);
  const clearPendingInterrupt = useChatStore(
    (state) => state.clearPendingInterrupt,
  );
  const replaceRecoveredInterrupts = useChatStore(
    (state) => state.replaceRecoveredInterrupts,
  );
  const setWorkingDirectory = useChatStore(
    (state) => state.setWorkingDirectory,
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
  const suppressAutoScrollRef = useRef(false);
  const shouldStickToBottomRef = useRef(true);
  const forceScrollToBottomRef = useRef(false);
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
  const workingDirectory = session?.workingDirectory ?? null;
  const invokeMetadataBindings = getInvokeMetadataBindings(session?.metadata);
  const extensionCapabilitiesQuery = useExtensionCapabilitiesQuery({
    agentId: activeAgentId,
    source: agent?.source,
    enabled: !isHubAssistantAgent,
  });
  const runtimeStatusContract = isHubAssistantAgent
    ? undefined
    : (extensionCapabilitiesQuery.runtimeStatusContract ?? undefined);
  const modelSelectionStatus: GenericCapabilityStatus = isHubAssistantAgent
    ? "unsupported"
    : !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.modelSelectionStatus;
  const providerDiscoveryStatus: GenericCapabilityStatus = isHubAssistantAgent
    ? "unsupported"
    : !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.providerDiscoveryStatus;
  const interruptRecoveryStatus: GenericCapabilityStatus = isHubAssistantAgent
    ? "unsupported"
    : !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.interruptRecoveryStatus;
  const sessionCommandStatus: GenericCapabilityStatus = isHubAssistantAgent
    ? "unsupported"
    : !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.sessionCommandStatus;
  const sessionShellStatus: GenericCapabilityStatus = isHubAssistantAgent
    ? "unsupported"
    : !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.sessionShellStatus;
  const sessionPromptAsyncStatus: GenericCapabilityStatus = isHubAssistantAgent
    ? "unsupported"
    : !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.sessionPromptAsyncStatus;
  const sessionAppendStatus: GenericCapabilityStatus = isHubAssistantAgent
    ? "unsupported"
    : !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.sessionAppendStatus;
  const sessionAppendRequiresStreamIdentity =
    !isHubAssistantAgent &&
    Boolean(
      activeAgentId &&
      agent?.source &&
      extensionCapabilitiesQuery.sessionAppend?.requiresStreamIdentity,
    );
  const invokeMetadataStatus: GenericCapabilityStatus = isHubAssistantAgent
    ? "unsupported"
    : !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.invokeMetadataStatus;
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

  const {
    sendHubAssistantMessage,
    handleHubAssistantPermissionReply,
    testHubAssistantConnection,
  } = useChatScreenHubAssistantController({
    activeAgentId,
    conversationId,
    isHubAssistantAgent,
    streamState: session?.streamState,
    lastAgentMessageId: session?.lastAgentMessageId ?? null,
    ensureSession,
    replaceRecoveredInterrupts,
  });
  const {
    canAppendToRunningStream,
    preemptRunningSession,
    sendMessageWithCapabilities,
  } = useChatScreenSessionController({
    session,
    pendingInterrupt,
    sessionAppendStatus,
    sessionAppendRequiresStreamIdentity,
    sessionCommandStatus,
    runtimeStatusContract,
    sendHubAssistantMessage,
    sendMessage,
  });

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
        if (nextAgentSource !== "personal" && nextAgentSource !== "shared") {
          return;
        }
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
    agentSource:
      agent?.source === "personal" || agent?.source === "shared"
        ? agent.source
        : null,
    conversationId,
    pendingInterrupt,
    lastResolvedInterrupt,
    pendingQuestionCount,
    workingDirectory,
    clearPendingInterrupt,
    onPermissionReplyOverride: isHubAssistantAgent
      ? handleHubAssistantPermissionReply
      : null,
    permissionReplySuccessMessage: isHubAssistantAgent
      ? "Permission request handled."
      : null,
  });

  const streamSendHint = useMemo(() => {
    if (pendingInterrupt) {
      return null;
    }
    if (session?.streamState === "continuing") {
      return {
        tone: "interrupt" as const,
        message:
          "The assistant is still finishing the approved action. Wait for it to complete before sending a new message.",
      };
    }
    if (session?.streamState !== "streaming") {
      return null;
    }
    if (canAppendToRunningStream) {
      return {
        tone: "append" as const,
        message:
          "This response is still running. Sending will add to it. Interrupt first if you want to start a new turn.",
      };
    }
    return {
      tone: "interrupt" as const,
      message:
        "The agent is still working. Interrupt it before sending a new message.",
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
  } = useChatComposerController({
    activeAgentId,
    conversationId,
    agentSource: agent?.source,
    pendingInterruptActive: pendingInterruptCount > 0,
    ensureSession,
    sendMessage: sendMessageWithCapabilities,
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
    if (!conversationId || !activeAgentId || isHubAssistantAgent) return;
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
        const normalizedBinding = buildContinueBindingPayload(
          boundAgentId,
          binding,
        );
        const current = useChatStore.getState().sessions[conversationId];
        const hasLocalBinding =
          (typeof current?.externalSessionRef?.externalSessionId === "string" &&
            current.externalSessionRef.externalSessionId.trim()) ||
          Object.keys(current?.metadata ?? {}).length > 0;
        const hasBindingMetadata =
          normalizedBinding.externalSessionId || normalizedBinding.provider;
        if (hasLocalBinding && !hasBindingMetadata) {
          return;
        }
        ensureSession(conversationId, boundAgentId);
        useChatStore
          .getState()
          .bindExternalSession(conversationId, normalizedBinding);
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
    isHubAssistantAgent,
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
      !boundExternalSessionId ||
      isHubAssistantAgent
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
      (!isHubAssistantAgent && (!agent?.source || !boundExternalSessionId))
    ) {
      return;
    }
    if (isHubAssistantAgent) {
      return;
    }
    const nextAgentSource = agent?.source;
    if (nextAgentSource !== "personal" && nextAgentSource !== "shared") {
      return;
    }
    recoverPendingInterrupts({
      nextConversationId: conversationId,
      nextAgentId: activeAgentId,
      nextAgentSource,
      nextSessionId: boundExternalSessionId,
    });
  }, [
    activeAgentId,
    agent?.source,
    boundExternalSessionId,
    conversationId,
    isHubAssistantAgent,
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
        !isHubAssistantAgent &&
        agent?.source &&
        boundExternalSessionId &&
        interruptRecoveryStatus === "supported"
      ) {
        if (agent.source !== "personal" && agent.source !== "shared") {
          return;
        }
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
      isHubAssistantAgent,
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
        session?.streamState === "continuing" ||
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
      if (isHubAssistantAgent) {
        await testHubAssistantConnection();
        return;
      }
      await validateAgentMutation.mutateAsync(activeAgentId);
      toast.success("Connection OK", `${agent.name} is online.`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Connection failed.";
      toast.error("Test failed", message);
    }
  }, [
    activeAgentId,
    agent,
    isHubAssistantAgent,
    testHubAssistantConnection,
    validateAgentMutation,
  ]);

  useEffect(() => () => clearScrollSettleTimer(), [clearScrollSettleTimer]);

  const openSessionPicker = useCallback(() => {
    setShowSessionPicker(true);
  }, []);

  const closeSessionPicker = useCallback(() => {
    setShowSessionPicker(false);
  }, []);

  const handleSaveWorkingDirectory = useCallback(
    (directory: string) => {
      if (!conversationId || !activeAgentId) {
        return;
      }
      ensureSession(conversationId, activeAgentId);
      setWorkingDirectory(conversationId, activeAgentId, directory);
      toast.success("Working directory updated", directory);
    },
    [activeAgentId, conversationId, ensureSession, setWorkingDirectory],
  );

  const handleClearWorkingDirectory = useCallback(() => {
    if (!conversationId || !activeAgentId) {
      return;
    }
    ensureSession(conversationId, activeAgentId);
    setWorkingDirectory(conversationId, activeAgentId, null);
    toast.success("Working directory cleared", "Using upstream default.");
  }, [activeAgentId, conversationId, ensureSession, setWorkingDirectory]);

  const openInvokeMetadataModal = useCallback(() => {
    setShowInvokeMetadataModal(true);
  }, []);

  const closeInvokeMetadataModal = useCallback(() => {
    setShowInvokeMetadataModal(false);
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
      session?.streamState === "streaming" ||
      session?.streamState === "continuing"
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
    if (
      !conversationId ||
      !activeAgentId ||
      (agent?.source !== "personal" && agent?.source !== "shared")
    ) {
      return;
    }
    const runInterrupt = async () => {
      try {
        await preemptRunningSession(
          conversationId,
          activeAgentId,
          agent.source,
        );
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Unable to interrupt response.";
        toast.error("Interrupt failed", message);
      }
    };
    runInterrupt();
  }, [activeAgentId, agent?.source, conversationId, preemptRunningSession]);

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
    interruptRecoveryStatus,
    sessionCommandStatus,
    sessionShellStatus,
    sessionPromptAsyncStatus,
    sessionAppendStatus,
    invokeMetadataStatus,
    selectedModel,
    workingDirectory,
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
    showDirectoryPicker,
    showModelPicker,
    openShortcutManager,
    closeShortcutManager,
    openSessionPicker,
    closeSessionPicker,
    openInvokeMetadataModal,
    closeInvokeMetadataModal,
    openDirectoryPicker,
    closeDirectoryPicker,
    openModelPicker,
    closeModelPicker,
    handleModelSelect,
    clearModelSelection,
    handleSaveWorkingDirectory,
    handleClearWorkingDirectory,
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
