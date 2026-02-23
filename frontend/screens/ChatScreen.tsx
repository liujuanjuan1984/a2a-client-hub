import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
  Pressable,
  Text,
  TextInput,
  TextInputKeyPressEventData,
  View,
} from "react-native";

import { ChatMessageItem } from "@/components/chat/ChatMessageItem";
import { InterruptActionCard } from "@/components/chat/InterruptActionCard";
import { SessionPickerModal } from "@/components/chat/SessionPickerModal";
import { ShortcutManagerModal } from "@/components/chat/ShortcutManagerModal";
import { PAGE_TOP_OFFSET } from "@/components/layout/spacing";
import { useAppSafeArea } from "@/components/layout/useAppSafeArea";
import { BackButton } from "@/components/ui/BackButton";
import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
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
import { shouldStickToBottom } from "@/lib/chatScroll";
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
const LIST_INITIAL_NUM_TO_RENDER = 16;
const LIST_WINDOW_SIZE = 9;
const LIST_MAX_TO_RENDER_PER_BATCH = 20;
const SEND_SCROLL_SETTLE_MS = Platform.OS === "ios" ? 120 : 60;

export function ChatScreen({
  agentId: routeAgentId,
  conversationId,
}: {
  agentId?: string | null;
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
    const hasHistory =
      messages.length > 0 || sessionHistoryQuery.messages.length > 0;
    if (sessionSource === "manual" && !hasHistory) {
      return;
    }

    let cancelled = false;
    continueSession(conversationId)
      .then((binding) => {
        if (cancelled) return;
        const current = useChatStore.getState().sessions[conversationId];
        const hasLocalBinding =
          (typeof current?.contextId === "string" &&
            current.contextId.trim()) ||
          (typeof current?.externalSessionRef?.externalSessionId === "string" &&
            current.externalSessionRef.externalSessionId.trim()) ||
          Object.keys(current?.metadata ?? {}).length > 0;
        if (hasLocalBinding && !binding.metadata?.contextId) {
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
      // Redirect: the agent is missing, so we should not keep this screen in history.
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
    // Reset initial load flag when conversation changes
    isInitialLoadRef.current = true;
  }, [conversationId]);

  const handleListContentSizeChange = useCallback(
    (_w: number, h: number) => {
      const anchor = prependAnchorRef.current ?? contentSizeAnchorRef.current;
      if (anchor) {
        const delta = h - anchor.contentHeight;
        listRef.current?.scrollToOffset({
          offset: Math.max(0, anchor.offset + delta),
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

  const handleTest = async () => {
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
  };

  const handleSend = () => {
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
  };

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

  const openShortcutManager = () => setShowShortcutManager(true);
  const openSessionPicker = () => setShowSessionPicker(true);
  const closeSessionPicker = () => setShowSessionPicker(false);
  const closeShortcutManager = () => setShowShortcutManager(false);

  const handleUseShortcut = (prompt: string) => {
    setInput(prompt);
    closeShortcutManager();
    inputRef.current?.focus();
  };

  const handleInputChange = (value: string) => {
    setInput(value);
    if (!value) {
      setInputHeight(minInputHeight);
    }
  };

  const handleContentSizeChange = (height: number) => {
    const nextHeight = Math.min(
      maxInputHeight,
      Math.max(minInputHeight, Math.ceil(height)),
    );
    setInputHeight((prev) => (prev === nextHeight ? prev : nextHeight));
  };

  const handleKeyPress = (
    e: NativeSyntheticEvent<TextInputKeyPressEventData>,
  ) => {
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
  };

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

  if (!agent) {
    if (!hasFetchedAgents) {
      return <FullscreenLoader message="Restoring session..." />;
    }
    return (
      <View className="flex-1 items-center justify-center bg-background px-6">
        <Text className="text-xl font-semibold text-white">
          Select an agent first
        </Text>
        <Text className="mt-2 text-center text-sm text-muted">
          Choose an agent from the list to start chatting.
        </Text>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      className="flex-1 bg-background"
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View
        className="border-b border-slate-800 bg-background/80 px-6 pb-4"
        style={{ paddingTop: insets.top + PAGE_TOP_OFFSET }}
      >
        <View className="flex-row items-center justify-between">
          <View className="flex-1 flex-row items-center gap-2">
            <View>
              <Text className="text-lg font-bold text-white" numberOfLines={1}>
                {agent.name}
              </Text>
            </View>
          </View>
          <View className="flex-row items-center gap-3">
            <BackButton />
            <Pressable
              className="h-10 w-10 items-center justify-center rounded-full bg-primary"
              onPress={openSessionPicker}
              accessibilityRole="button"
              accessibilityLabel="Show sessions"
              accessibilityHint="View and switch chat sessions"
            >
              <Ionicons name="list" size={20} color="#ffffff" />
            </Pressable>
            <Pressable
              className={`h-10 w-10 items-center justify-center rounded-full border border-slate-700 ${
                showDetails ? "bg-slate-700" : ""
              }`}
              onPress={() => setShowDetails(!showDetails)}
              accessibilityRole="button"
              accessibilityLabel="Toggle details"
              accessibilityHint="Show or hide session details"
            >
              <Ionicons
                name={
                  showDetails
                    ? "information-circle"
                    : "information-circle-outline"
                }
                size={20}
                color="#ffffff"
              />
            </Pressable>
          </View>
        </View>

        {showDetails ? (
          <View className="mt-4 gap-4 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
            <View>
              <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                Agent Endpoint
              </Text>
              <Text className="mt-1 break-all text-xs text-white">
                {agent.cardUrl}
              </Text>
            </View>

            <View className="h-[1px] bg-slate-800" />

            <View className="flex-row flex-wrap gap-4">
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Conversation ID
                </Text>
                <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                  {conversationId ?? "N/A"}
                </Text>
              </View>
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Source
                </Text>
                <Text className="mt-1 text-xs text-white">
                  {sessionSource ?? "N/A"}
                </Text>
              </View>
            </View>

            <View className="h-[1px] bg-slate-800" />

            <View className="flex-row flex-wrap gap-4">
              {session?.runtimeStatus ? (
                <View className="flex-1 min-w-[45%]">
                  <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                    Runtime
                  </Text>
                  <Text className="mt-1 text-xs text-white">
                    {session.runtimeStatus}
                  </Text>
                </View>
              ) : null}
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Transport
                </Text>
                <Text className="mt-1 text-xs text-white">
                  {session?.transport ?? "N/A"}
                </Text>
              </View>
              {session?.contextId ? (
                <View className="flex-1 min-w-[45%]">
                  <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                    Context ID
                  </Text>
                  <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                    {session.contextId}
                  </Text>
                </View>
              ) : null}
              {session?.externalSessionRef?.provider ? (
                <View className="flex-1 min-w-[45%]">
                  <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                    Provider
                  </Text>
                  <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                    {session.externalSessionRef.provider}
                  </Text>
                </View>
              ) : null}
              {session?.externalSessionRef?.externalSessionId ? (
                <View className="flex-1 min-w-[45%]">
                  <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                    External Session
                  </Text>
                  <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                    {session.externalSessionRef.externalSessionId}
                  </Text>
                </View>
              ) : null}
            </View>

            <View className="h-[1px] bg-slate-800" />

            <View className="flex-row items-center justify-between">
              <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                Diagnostics
              </Text>
              <Button
                label="Test Connection"
                size="sm"
                variant="secondary"
                iconLeft="pulse-outline"
                loading={validateAgentMutation.isPending}
                onPress={handleTest}
              />
            </View>

            <View className="h-[1px] bg-slate-800" />

            <View>
              <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                Capabilities
              </Text>
              <View className="mt-2 flex-row flex-wrap gap-2">
                {(session?.inputModes ?? ["text"]).map((mode) => (
                  <View key={mode} className="rounded bg-slate-800 px-2 py-1">
                    <Text className="text-[9px] text-white">IN: {mode}</Text>
                  </View>
                ))}
                {(session?.outputModes ?? ["text"]).map((mode) => (
                  <View key={mode} className="rounded bg-primary/20 px-2 py-1">
                    <Text className="text-[9px] text-primary">OUT: {mode}</Text>
                  </View>
                ))}
              </View>
            </View>

            {session?.externalSessionRef?.externalSessionId ? (
              <>
                <View className="h-[1px] bg-slate-800" />
                <Text className="text-xs text-muted">
                  External history is shown inline in this chat.
                </Text>
              </>
            ) : null}
          </View>
        ) : null}
      </View>

      {session?.streamState === "recoverable" ? (
        <View className="mx-6 mt-3 flex-row items-center rounded-xl border border-yellow-500/30 bg-yellow-500/10 px-3 py-2">
          <ActivityIndicator size="small" color="#fcd34d" className="mr-2" />
          <Text className="text-xs text-yellow-300">
            Connection lost. Trying to recover the stream...
          </Text>
        </View>
      ) : null}

      {session?.streamState === "error" ? (
        <View className="mx-6 mt-3 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2">
          <Text className="text-xs text-red-300">
            Session recovery failed.
            {session.lastStreamError ? ` ${session.lastStreamError}` : ""}
          </Text>
        </View>
      ) : null}

      <FlatList
        ref={listRef}
        className="mt-2 flex-1 px-6"
        data={messages ?? []}
        keyExtractor={(item) => item.id}
        renderItem={({ item, index }) => (
          <ChatMessageItem
            message={item}
            index={index}
            isLastMessage={index === messages.length - 1}
            sessionStreamState={session?.streamState}
            onLayoutChangeStart={captureContentSizeAnchor}
            onRetry={handleRetry}
          />
        )}
        contentContainerStyle={{ paddingBottom: 24 }}
        keyboardShouldPersistTaps="handled"
        initialNumToRender={LIST_INITIAL_NUM_TO_RENDER}
        maxToRenderPerBatch={LIST_MAX_TO_RENDER_PER_BATCH}
        windowSize={LIST_WINDOW_SIZE}
        updateCellsBatchingPeriod={50}
        removeClippedSubviews={Platform.OS === "android"}
        onContentSizeChange={handleListContentSizeChange}
        onScroll={handleListScroll}
        scrollEventThrottle={16}
        ListHeaderComponent={
          typeof historyNextPage === "number" ? (
            <View className="items-center">
              <Button
                className="mt-2"
                label={historyLoadingMore ? "Loading..." : "Load earlier"}
                size="sm"
                variant="secondary"
                loading={historyLoadingMore}
                disabled={historyPaused}
                onPress={loadEarlierHistory}
              />
            </View>
          ) : null
        }
        ListEmptyComponent={
          <View className="mt-12 items-center">
            <Text className="text-sm text-muted">
              {historyLoading
                ? "Loading history..."
                : historyError
                  ? historyError
                  : "No messages yet."}
            </Text>
          </View>
        }
        ListFooterComponent={
          pendingInterrupt ? (
            <InterruptActionCard
              pendingInterrupt={pendingInterrupt}
              interruptAction={interruptAction}
              questionAnswers={questionAnswers}
              onPermissionReply={handlePermissionReply}
              onQuestionAnswerChange={handleQuestionAnswerChange}
              onQuestionOptionPick={handleQuestionOptionPick}
              onQuestionReply={handleQuestionReply}
              onQuestionReject={handleQuestionReject}
            />
          ) : null
        }
      />

      <View className="relative border-t border-slate-800 px-6 py-4">
        {pendingInterrupt ? (
          <View className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2">
            <Text className="text-xs text-amber-200">
              Agent is waiting for authorization/input. Resolve the action card
              first.
            </Text>
          </View>
        ) : null}

        <ShortcutManagerModal
          visible={showShortcutManager}
          onClose={closeShortcutManager}
          onUseShortcut={handleUseShortcut}
          initialPrompt={input}
          agentId={activeAgentId}
        />

        <SessionPickerModal
          visible={showSessionPicker}
          onClose={closeSessionPicker}
          agentId={activeAgentId}
          currentConversationId={conversationId}
          onSelect={(nextConversationId) => {
            blurActiveElement();
            router.replace(buildChatRoute(agent.id, nextConversationId));
          }}
        />

        <View className="flex-row items-end gap-2 bg-slate-900/50 p-2 rounded-3xl border border-slate-800">
          <Pressable
            className={`h-9 w-9 items-center justify-center rounded-xl ${
              showShortcutManager ? "bg-primary" : "bg-slate-800"
            }`}
            onPress={openShortcutManager}
            accessibilityRole="button"
            accessibilityLabel="Open shortcut manager"
          >
            <Ionicons
              name={showShortcutManager ? "flash" : "flash-outline"}
              size={18}
              color={showShortcutManager ? "#ffffff" : "#94a3b8"}
            />
          </Pressable>
          <TextInput
            ref={inputRef}
            className="flex-1 px-3 py-2 text-white"
            placeholder="Type your message"
            placeholderTextColor="#6b7280"
            multiline
            value={input}
            onChangeText={handleInputChange}
            onContentSizeChange={(event) =>
              handleContentSizeChange(event.nativeEvent.contentSize.height)
            }
            scrollEnabled={inputHeight >= maxInputHeight}
            textAlignVertical="top"
            style={{ height: inputHeight, fontSize: 16 }}
            submitBehavior={Platform.OS === "web" ? "submit" : undefined}
            onSubmitEditing={Platform.OS === "web" ? undefined : handleSend}
            onKeyPress={handleKeyPress}
            blurOnSubmit={false}
            returnKeyType="default"
          />
          <Pressable
            className={`h-9 w-9 items-center justify-center rounded-xl ${
              !input.trim() || Boolean(pendingInterrupt)
                ? "bg-slate-800 opacity-50"
                : "bg-primary"
            }`}
            testID="chat-send-button"
            onPress={handleSend}
            disabled={!input.trim() || Boolean(pendingInterrupt)}
            accessibilityRole="button"
            accessibilityLabel="Send message"
          >
            <Ionicons name="send" size={16} color="#ffffff" />
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}
