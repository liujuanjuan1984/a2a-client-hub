import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FlatList,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
  TextInput,
  TextInputKeyPressEventData,
} from "react-native";

import { PAGE_TOP_OFFSET } from "@/components/layout/spacing";
import { useAppSafeArea } from "@/components/layout/useAppSafeArea";
import {
  useAgentsCatalogQuery,
  useValidateAgentMutation,
} from "@/hooks/useAgentsCatalogQuery";
import { useSessionHistoryQuery } from "@/hooks/useChatHistoryQuery";
import { useRefreshOnFocus } from "@/hooks/useRefreshOnFocus";
import {
  A2AExtensionCallError,
  rejectOpencodeQuestionInterrupt,
  replyOpencodePermissionInterrupt,
  replyOpencodeQuestionInterrupt,
} from "@/lib/api/a2aExtensions";
import { type ChatMessage } from "@/lib/api/chat-utils";
import { ApiRequestError } from "@/lib/api/client";
import { continueSession } from "@/lib/api/sessions";
import { isSameMessageList } from "@/lib/chat-utils";
import {
  getAnchoredOffsetAfterContentResize,
  shouldStickToBottom,
} from "@/lib/chatScroll";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { buildContinueBindingPayload } from "@/lib/sessionBinding";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useMessageStore } from "@/store/messages";
import { useShortcutStore } from "@/store/shortcuts";

type WebTextInputKeyPressEvent =
  NativeSyntheticEvent<TextInputKeyPressEventData> & {
    nativeEvent: TextInputKeyPressEventData & {
      shiftKey?: boolean;
      isComposing?: boolean;
    };
    preventDefault?: () => void;
  };

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
  const clearPendingInterrupt = useChatStore(
    (state) => state.clearPendingInterrupt,
  );
  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );
  const setMessages = useMessageStore((state) => state.setMessages);
  const messages = useMessageStore((state) =>
    conversationId ? (state.messages[conversationId] ?? []) : [],
  );
  const { syncShortcuts } = useShortcutStore();

  const [input, setInput] = useState("");
  const suppressAutoScrollRef = useRef(false);
  const shouldStickToBottomRef = useRef(true);
  const forceScrollToBottomRef = useRef(false);
  const scrollSettleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const [showDetails, setShowDetails] = useState(false);
  const [showShortcutManager, setShowShortcutManager] = useState(false);
  const [showSessionPicker, setShowSessionPicker] = useState(false);
  const [interruptAction, setInterruptAction] = useState<string | null>(null);
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);

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
  const inputRef = useRef<TextInput>(null);
  const isInitialLoadRef = useRef(true);
  const minInputHeight = 44;
  const maxInputHeight = 128;
  const [inputHeight, setInputHeight] = useState(minInputHeight);
  const historyPaused = session?.streamState === "streaming";

  const sessionHistoryQuery = useSessionHistoryQuery({
    conversationId,
    enabled: Boolean(conversationId),
    paused: historyPaused,
  });

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
  const pendingQuestionCount =
    pendingInterrupt?.type === "question"
      ? (pendingInterrupt.details.questions?.length ?? 0)
      : 0;

  const buildInterruptErrorMessage = useCallback((error: unknown) => {
    if (error instanceof ApiRequestError) {
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
    }

    if (error instanceof A2AExtensionCallError) {
      return error.errorCode
        ? `${error.message}: ${error.errorCode}`
        : error.message;
    }
    return error instanceof Error
      ? error.message
      : "Interrupt callback failed.";
  }, []);

  const clearScrollSettleTimer = useCallback(() => {
    if (scrollSettleTimerRef.current) {
      clearTimeout(scrollSettleTimerRef.current);
      scrollSettleTimerRef.current = null;
    }
  }, []);

  const scrollToBottom = useCallback((animated: boolean) => {
    listRef.current?.scrollToEnd({ animated });
  }, []);

  const scheduleStickToBottom = useCallback(
    (animated: boolean) => {
      if (!shouldStickToBottomRef.current && !forceScrollToBottomRef.current) {
        return;
      }
      requestAnimationFrame(() => {
        scrollToBottom(animated);
      });
      clearScrollSettleTimer();
      scrollSettleTimerRef.current = setTimeout(() => {
        scrollToBottom(false);
        forceScrollToBottomRef.current = false;
      }, SEND_SCROLL_SETTLE_MS);
    },
    [clearScrollSettleTimer, scrollToBottom],
  );

  useEffect(() => {
    if (activeAgentId && conversationId) {
      ensureSession(conversationId, activeAgentId);
    }
  }, [activeAgentId, conversationId, ensureSession]);

  useEffect(() => {
    syncShortcuts().catch(() => {
      // Keep shortcut sync failure non-blocking for UX.
    });
  }, [syncShortcuts]);

  useEffect(() => {
    if (!conversationId || !activeAgentId) return;
    const boundAgentId = activeAgentId;
    const normalizedConversationId = conversationId;
    const hasHistory =
      messages.length > 0 || sessionHistoryQuery.messages.length > 0;
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
    sessionHistoryQuery.messages.length,
    conversationId,
    router,
    sessionSource,
  ]);

  const mergeHistoryMessages = useCallback(
    (incoming: ChatMessage[]) => {
      if (!conversationId) return;
      const current = useMessageStore.getState().messages[conversationId] ?? [];
      const merged = new Map<string, ChatMessage>();
      current.forEach((message) => {
        merged.set(message.id, message);
      });
      incoming.forEach((message) => {
        const existing = merged.get(message.id);
        const isActivelyStreaming = session?.streamState === "streaming";
        if (
          existing &&
          existing.status === "streaming" &&
          isActivelyStreaming
        ) {
          return;
        }
        merged.set(message.id, message);
      });
      const nextMessages = Array.from(merged.values()).sort((a, b) =>
        a.createdAt.localeCompare(b.createdAt),
      );
      if (isSameMessageList(current, nextMessages)) {
        return;
      }
      setMessages(conversationId, nextMessages);
    },
    [conversationId, setMessages, session?.streamState],
  );

  useEffect(() => {
    if (!conversationId) return;
    if (sessionHistoryQuery.messages.length === 0) return;
    mergeHistoryMessages(sessionHistoryQuery.messages);
  }, [mergeHistoryMessages, conversationId, sessionHistoryQuery.messages]);

  useEffect(() => {
    if (!pendingInterrupt || pendingInterrupt.type !== "question") {
      setQuestionAnswers([]);
      return;
    }
    setQuestionAnswers((current) =>
      Array.from(
        { length: pendingQuestionCount },
        (_, index) => current[index] ?? "",
      ),
    );
  }, [
    pendingInterrupt?.requestId,
    pendingInterrupt?.type,
    pendingQuestionCount,
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

  const handleSend = useCallback(() => {
    if (!activeAgentId || !conversationId || !agent) {
      return;
    }
    if (pendingInterrupt) {
      toast.info(
        "Action required",
        "Please resolve the interactive action card before sending a new message.",
      );
      return;
    }
    if (!input.trim()) {
      return;
    }
    forceScrollToBottomRef.current = true;
    shouldStickToBottomRef.current = true;
    sendMessage(conversationId, activeAgentId, input, agent.source);
    setInput("");
    setInputHeight(minInputHeight);
    scheduleStickToBottom(true);
  }, [
    activeAgentId,
    agent,
    conversationId,
    input,
    pendingInterrupt,
    scheduleStickToBottom,
    sendMessage,
  ]);

  const runInterruptAction = useCallback(
    async (
      actionKey: string,
      executor: () => Promise<void>,
      successMessage: string,
    ) => {
      setInterruptAction(actionKey);
      try {
        await executor();
        toast.success("Action submitted", successMessage);
      } catch (error) {
        toast.error(
          "Interrupt callback failed",
          buildInterruptErrorMessage(error),
        );
      } finally {
        setInterruptAction(null);
      }
    },
    [buildInterruptErrorMessage],
  );

  const handlePermissionReply = useCallback(
    (reply: "once" | "always" | "reject") => {
      if (!activeAgentId || !conversationId || !pendingInterrupt || !agent) {
        return;
      }
      if (pendingInterrupt.type !== "permission") {
        return;
      }
      const requestId = pendingInterrupt.requestId;
      runInterruptAction(
        `permission:${reply}`,
        async () => {
          await replyOpencodePermissionInterrupt({
            source: agent.source,
            agentId: activeAgentId,
            requestId,
            reply,
          });
          clearPendingInterrupt(conversationId, requestId);
        },
        "Permission reply delivered to upstream.",
      ).catch(() => undefined);
    },
    [
      activeAgentId,
      agent,
      clearPendingInterrupt,
      conversationId,
      pendingInterrupt,
      runInterruptAction,
    ],
  );

  const handleQuestionAnswerChange = useCallback(
    (index: number, value: string) => {
      setQuestionAnswers((current) => {
        const next = [...current];
        next[index] = value;
        return next;
      });
    },
    [],
  );

  const handleQuestionOptionPick = useCallback(
    (index: number, value: string) => {
      setQuestionAnswers((current) => {
        const next = [...current];
        next[index] = value;
        return next;
      });
    },
    [],
  );

  const handleQuestionReply = useCallback(() => {
    if (!activeAgentId || !conversationId || !pendingInterrupt || !agent) {
      return;
    }
    if (pendingInterrupt.type !== "question") {
      return;
    }
    const questions = pendingInterrupt.details.questions ?? [];
    const normalizedAnswers = questions.map((_, index) => {
      const answer = questionAnswers[index]?.trim() ?? "";
      return answer ? [answer] : [];
    });
    if (normalizedAnswers.some((group) => group.length === 0)) {
      toast.error("Missing answer", "Please answer all questions first.");
      return;
    }
    const requestId = pendingInterrupt.requestId;
    runInterruptAction(
      "question:reply",
      async () => {
        await replyOpencodeQuestionInterrupt({
          source: agent.source,
          agentId: activeAgentId,
          requestId,
          answers: normalizedAnswers,
        });
        clearPendingInterrupt(conversationId, requestId);
      },
      "Question answers delivered to upstream.",
    ).catch(() => undefined);
  }, [
    activeAgentId,
    agent,
    clearPendingInterrupt,
    conversationId,
    pendingInterrupt,
    questionAnswers,
    runInterruptAction,
  ]);

  const handleQuestionReject = useCallback(() => {
    if (!activeAgentId || !conversationId || !pendingInterrupt || !agent) {
      return;
    }
    if (pendingInterrupt.type !== "question") {
      return;
    }
    const requestId = pendingInterrupt.requestId;
    runInterruptAction(
      "question:reject",
      async () => {
        await rejectOpencodeQuestionInterrupt({
          source: agent.source,
          agentId: activeAgentId,
          requestId,
        });
        clearPendingInterrupt(conversationId, requestId);
      },
      "Question request rejected.",
    ).catch(() => undefined);
  }, [
    activeAgentId,
    agent,
    clearPendingInterrupt,
    conversationId,
    pendingInterrupt,
    runInterruptAction,
  ]);

  useEffect(() => () => clearScrollSettleTimer(), [clearScrollSettleTimer]);

  const openShortcutManager = useCallback(() => {
    setShowShortcutManager(true);
  }, []);

  const closeShortcutManager = useCallback(() => {
    setShowShortcutManager(false);
  }, []);

  const openSessionPicker = useCallback(() => {
    setShowSessionPicker(true);
  }, []);

  const closeSessionPicker = useCallback(() => {
    setShowSessionPicker(false);
  }, []);

  const handleUseShortcut = useCallback(
    (prompt: string) => {
      setInput(prompt);
      closeShortcutManager();
      inputRef.current?.focus();
    },
    [closeShortcutManager],
  );

  const handleInputChange = useCallback(
    (value: string) => {
      setInput(value);
      if (!value) {
        setInputHeight(minInputHeight);
      }
    },
    [minInputHeight],
  );

  const handleContentSizeChange = useCallback(
    (height: number) => {
      const nextHeight = Math.min(
        maxInputHeight,
        Math.max(minInputHeight, Math.ceil(height)),
      );
      setInputHeight((prev) => (prev === nextHeight ? prev : nextHeight));
    },
    [maxInputHeight, minInputHeight],
  );

  const handleKeyPress = useCallback(
    (e: NativeSyntheticEvent<TextInputKeyPressEventData>) => {
      const webEvent = e as WebTextInputKeyPressEvent;
      if (
        Platform.OS === "web" &&
        webEvent.nativeEvent.key === "Enter" &&
        !webEvent.nativeEvent.shiftKey &&
        !webEvent.nativeEvent.isComposing
      ) {
        webEvent.preventDefault?.();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleRetry = useCallback(() => {
    if (
      !conversationId ||
      !activeAgentId ||
      session?.streamState === "streaming"
    )
      return;
    const lastMessage = messages[messages.length - 1];
    if (lastMessage?.role === "user") {
      sendMessage(
        conversationId,
        activeAgentId,
        lastMessage.content,
        agent?.source || "personal",
      );
    } else {
      const lastUserMessage = [...messages]
        .reverse()
        .find((m) => m.role === "user");
      if (lastUserMessage) {
        sendMessage(
          conversationId,
          activeAgentId,
          lastUserMessage.content,
          agent?.source || "personal",
        );
      }
    }
  }, [
    activeAgentId,
    agent?.source,
    conversationId,
    messages,
    sendMessage,
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
    showShortcutManager,
    showSessionPicker,
    openShortcutManager,
    closeShortcutManager,
    openSessionPicker,
    closeSessionPicker,
    handleUseShortcut,
    handleSessionSelect,
    handleTest,
    testingConnection: validateAgentMutation.isPending,
    listRef,
    inputRef,
    input,
    inputHeight,
    maxInputHeight,
    handleInputChange,
    handleContentSizeChange,
    handleKeyPress,
    handleSend,
    loadEarlierHistory,
    handleListContentSizeChange,
    handleListScroll,
    captureContentSizeAnchor,
    handleRetry,
    handlePermissionReply,
    handleQuestionAnswerChange,
    handleQuestionOptionPick,
    handleQuestionReply,
    handleQuestionReject,
  };
}
