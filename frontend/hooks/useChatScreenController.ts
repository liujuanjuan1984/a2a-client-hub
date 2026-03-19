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
import type { ChatMessage } from "@/lib/api/chat-utils";
import { continueSession } from "@/lib/api/sessions";
import { getSharedModelSelection } from "@/lib/chat-utils";
import {
  getAnchoredOffsetAfterContentResize,
  shouldShowScrollToBottom,
  shouldStickToBottom,
} from "@/lib/chatScroll";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { buildContinueBindingPayload } from "@/lib/sessionBinding";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";

const HISTORY_AUTOLOAD_THRESHOLD = 72;
const SEND_SCROLL_SETTLE_MS = Platform.OS === "ios" ? 120 : 60;

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
  const clearPendingInterrupt = useChatStore(
    (state) => state.clearPendingInterrupt,
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
  const pendingInterrupt = session?.pendingInterrupt ?? null;
  const lastResolvedInterrupt = session?.lastResolvedInterrupt ?? null;
  const selectedModel = getSharedModelSelection(session?.metadata);
  const extensionCapabilitiesQuery = useExtensionCapabilitiesQuery({
    agentId: activeAgentId,
    source: agent?.source,
  });
  const modelSelectionStatus: GenericCapabilityStatus =
    !activeAgentId || !agent?.source
      ? "unsupported"
      : extensionCapabilitiesQuery.modelSelectionStatus;
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
    interruptAction,
    questionAnswers,
    handlePermissionReply,
    handleQuestionAnswerChange,
    handleQuestionOptionPick,
    handleQuestionReply,
    handleQuestionReject,
  } = useChatInterruptController({
    activeAgentId,
    agentSource: agent?.source,
    conversationId,
    pendingInterrupt,
    lastResolvedInterrupt,
    pendingQuestionCount,
    clearPendingInterrupt,
  });

  const {
    inputRef,
    inputResetKey,
    inputDefaultValue,
    hasInput,
    hasSendableInput,
    maxInputChars,
    shortcutManagerInitialPrompt,
    inputHeight,
    maxInputHeight,
    showShortcutManager,
    showModelPicker,
    openShortcutManager,
    closeShortcutManager,
    openModelPicker,
    closeModelPicker,
    handleModelSelect,
    clearModelSelection,
    handleUseShortcut,
    clearInput,
    handleInputChange,
    handleContentSizeChange,
    handleKeyPress,
    handleSend,
  } = useChatComposerController({
    activeAgentId,
    conversationId,
    agentSource: agent?.source,
    pendingInterruptActive: Boolean(pendingInterrupt),
    ensureSession,
    sendMessage,
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
          (typeof current?.contextId === "string" &&
            current.contextId.trim()) ||
          (typeof current?.externalSessionRef?.externalSessionId === "string" &&
            current.externalSessionRef.externalSessionId.trim()) ||
          Object.keys(current?.metadata ?? {}).length > 0;
        const hasBindingMetadata =
          (typeof binding.metadata?.contextId === "string" &&
            binding.metadata.contextId.trim()) ||
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
      forceScrollToBottomRef.current = true;
      shouldStickToBottomRef.current = true;
      scheduleStickToBottom(true);
    }, [conversationId, scheduleStickToBottom]),
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
            await resumeMessage(conversationId);
          }
          return;
        }
        if (typeof retryMessage === "function") {
          await retryMessage(
            conversationId,
            activeAgentId,
            agent?.source || "personal",
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
    retryMessage,
    resumeMessage,
    session?.streamState,
  ]);

  const toggleDetails = useCallback(() => {
    setShowDetails((current) => !current);
  }, []);

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
    selectedModel,
    messages,
    historyLoading,
    historyLoadingMore,
    historyNextPage,
    historyPaused,
    historyError,
    pendingInterrupt,
    interruptAction,
    questionAnswers,
    showDetails,
    toggleDetails,
    showScrollToBottom,
    scrollToBottom,
    showShortcutManager,
    showSessionPicker,
    showModelPicker,
    openShortcutManager,
    closeShortcutManager,
    openSessionPicker,
    closeSessionPicker,
    openModelPicker,
    closeModelPicker,
    handleModelSelect,
    clearModelSelection,
    handleUseShortcut,
    handleSessionSelect,
    handleTest,
    testingConnection: validateAgentMutation.isPending,
    listRef,
    inputRef,
    inputResetKey,
    inputDefaultValue,
    hasInput,
    hasSendableInput,
    maxInputChars,
    shortcutManagerInitialPrompt,
    inputHeight,
    maxInputHeight,
    clearInput,
    handleInputChange,
    handleContentSizeChange,
    handleKeyPress,
    handleSend,
    loadEarlierHistory,
    handleListContentSizeChange,
    handleListScroll,
    captureContentSizeAnchor,
    handleLoadBlockContent,
    handleRetry,
    handlePermissionReply,
    handleQuestionAnswerChange,
    handleQuestionOptionPick,
    handleQuestionReply,
    handleQuestionReject,
  };
}
