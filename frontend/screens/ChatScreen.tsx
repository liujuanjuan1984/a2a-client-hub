import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FlatList,
  KeyboardAvoidingView,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  TextInputKeyPressEventData,
  View,
} from "react-native";

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
import {
  A2AExtensionCallError,
  rejectOpencodeQuestionInterrupt,
  replyOpencodePermissionInterrupt,
  replyOpencodeQuestionInterrupt,
} from "@/lib/api/a2aExtensions";
import { type ChatMessage, type MessageBlock } from "@/lib/api/chat-utils";
import { continueSession } from "@/lib/api/sessions";
import { shouldStickToBottom } from "@/lib/chatScroll";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { buildContinueBindingPayload } from "@/lib/sessionBinding";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useMessageStore } from "@/store/messages";
import { useShortcutStore } from "@/store/shortcuts";

const isSameBlockList = (
  left: MessageBlock[] = [],
  right: MessageBlock[] = [],
) => {
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    const lhs = left[index];
    const rhs = right[index];
    if (!lhs || !rhs) return false;
    if (
      lhs.id !== rhs.id ||
      lhs.type !== rhs.type ||
      lhs.content !== rhs.content ||
      lhs.isFinished !== rhs.isFinished ||
      lhs.createdAt !== rhs.createdAt ||
      lhs.updatedAt !== rhs.updatedAt
    ) {
      return false;
    }
  }
  return true;
};

type WebTextInputKeyPressEvent =
  NativeSyntheticEvent<TextInputKeyPressEventData> & {
    nativeEvent: TextInputKeyPressEventData & {
      shiftKey?: boolean;
      isComposing?: boolean;
    };
    preventDefault?: () => void;
  };

const isSameMessageList = (left: ChatMessage[], right: ChatMessage[]) => {
  if (left.length !== right.length) return false;
  return left.every((message, index) => {
    const next = right[index];
    if (!next) return false;
    return (
      message.id === next.id &&
      message.role === next.role &&
      message.content === next.content &&
      message.createdAt === next.createdAt &&
      isSameBlockList(message.blocks, next.blocks) &&
      message.status === next.status
    );
  });
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
  agentId?: string;
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
  const generateConversationId = useChatStore(
    (state) => state.generateConversationId,
  );
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
  const { shortcuts, addShortcut, removeShortcut } = useShortcutStore();

  const [input, setInput] = useState("");
  const suppressAutoScrollRef = useRef(false);
  const shouldStickToBottomRef = useRef(true);
  const forceScrollToBottomRef = useRef(false);
  const scrollSettleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const [showDetails, setShowDetails] = useState(false);
  const [showPresets, setShowPresets] = useState(false);
  const [interruptAction, setInterruptAction] = useState<string | null>(null);
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);
  const [expandedReasoningByBlockId, setExpandedReasoningByBlockId] = useState<
    Record<string, boolean>
  >({});
  const [expandedToolCallByBlockId, setExpandedToolCallByBlockId] = useState<
    Record<string, boolean>
  >({});
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const scrollOffsetRef = useRef(0);
  const contentHeightRef = useRef(0);
  const prependAnchorRef = useRef<{
    offset: number;
    contentHeight: number;
  } | null>(null);
  const loadingEarlierRef = useRef(false);
  const inputRef = useRef<TextInput>(null);
  const isInitialLoadRef = useRef(true);
  const minInputHeight = 44;
  const maxInputHeight = 128;
  const [inputHeight, setInputHeight] = useState(minInputHeight);
  const historyPaused =
    session?.streamState === "streaming" ||
    session?.streamState === "rebinding";

  const sessionHistoryQuery = useSessionHistoryQuery({
    conversationId,
    enabled: Boolean(conversationId),
    paused: historyPaused,
  });

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
        if (hasLocalBinding && !binding.contextId) {
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
    [conversationId, setMessages],
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
    sessionHistoryQuery.loadMore,
    conversationId,
  ]);

  useEffect(() => {
    if (hasFetchedAgents && !agent) {
      // Redirect: the agent is missing, so we should not keep this screen in history.
      router.replace("/");
    }
  }, [agent, hasFetchedAgents, router]);

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
      const anchor = prependAnchorRef.current;
      if (anchor) {
        const delta = Math.max(0, h - anchor.contentHeight);
        listRef.current?.scrollToOffset({
          offset: Math.max(0, anchor.offset + delta),
          animated: false,
        });
        prependAnchorRef.current = null;
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

  const handleSelectPreset = (value: string) => {
    setInput(value);
    setShowPresets(false);
    inputRef.current?.focus();
  };

  const handleSaveShortcut = () => {
    if (!input.trim()) return;
    const label = input.slice(0, 15) + (input.length > 15 ? "..." : "");
    addShortcut(label, input.trim());
    setShowPresets(true);
    toast.success("Shortcut saved", `"${label}" is now available.`);
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

  const toggleReasoning = (blockId: string) => {
    setExpandedReasoningByBlockId((current) => ({
      ...current,
      [blockId]: !current[blockId],
    }));
  };

  const toggleToolCall = (blockId: string) => {
    setExpandedToolCallByBlockId((current) => ({
      ...current,
      [blockId]: !current[blockId],
    }));
  };

  const deriveRenderableBlocks = useCallback(
    (message: ChatMessage): MessageBlock[] => {
      const persisted = message.blocks ?? [];
      if (persisted.length > 0) {
        return persisted;
      }
      if (message.role === "agent" && message.content.trim()) {
        const now = message.createdAt;
        return [
          {
            id: `${message.id}:text`,
            type: "text",
            content: message.content,
            isFinished: message.status !== "streaming",
            createdAt: now,
            updatedAt: now,
          },
        ];
      }
      return [];
    },
    [],
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

  const handleCopyPayload = useCallback(async (text: string) => {
    if (Platform.OS === "web" && typeof navigator !== "undefined") {
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(text);
          return;
        } catch {
          // Fall back to Expo clipboard API when browser clipboard write is blocked.
        }
      }
    }

    await Clipboard.setStringAsync(text);
  }, []);

  const handleCopyMessage = useCallback(
    async (message: ChatMessage) => {
      try {
        let textToCopy = message.content;
        if (message.role === "agent" && message.blocks?.length) {
          const blockContent = message.blocks
            .map((b) => `[${b.type}]\n${b.content}`)
            .join("\n\n");
          if (blockContent) {
            textToCopy = `${blockContent}\n\n${textToCopy}`;
          }
        }
        await handleCopyPayload(textToCopy.trim());
        toast.success("Copied", "Message copied to clipboard.");
      } catch {
        toast.error("Copy failed", "Could not copy message.");
      }
    },
    [handleCopyPayload],
  );

  const renderChatMessage = useCallback(
    ({ item: message, index }: { item: ChatMessage; index: number }) => {
      const renderableBlocks = deriveRenderableBlocks(message);
      const hasBlocks = message.role === "agent" && renderableBlocks.length > 0;
      const isLastMessage = index === messages.length - 1;
      const canRetry =
        isLastMessage &&
        message.role === "agent" &&
        session?.streamState !== "streaming";

      return (
        <View
          className={`mb-3 flex ${
            message.role === "user" ? "items-end" : "items-start"
          }`}
        >
          <View className="max-w-[94%]">
            <Pressable
              onLongPress={() => handleCopyMessage(message)}
              delayLongPress={500}
              className={`px-4 py-3 ${
                message.role === "user"
                  ? "rounded-2xl rounded-tr-sm bg-primary"
                  : message.role === "agent"
                    ? "rounded-2xl rounded-tl-sm bg-slate-800"
                    : "rounded-2xl bg-slate-900"
              }`}
            >
              {hasBlocks ? (
                renderableBlocks.map((block, blockIndex) => {
                  const blockText = block.content;
                  if (blockText.length === 0) return null;
                  const blockId = block.id || `${message.id}:${blockIndex}`;
                  if (block.type === "reasoning") {
                    const expanded = expandedReasoningByBlockId[blockId];
                    return (
                      <View
                        key={blockId}
                        className={`${
                          blockIndex > 0 ? "mt-3" : ""
                        } rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2`}
                      >
                        <Pressable onPress={() => toggleReasoning(blockId)}>
                          <Text className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                            {expanded ? "Hide Reasoning" : "Show Reasoning"}
                          </Text>
                        </Pressable>
                        {expanded ? (
                          <Text
                            selectable
                            className="mt-1 break-all text-xs text-slate-300"
                          >
                            {blockText}
                          </Text>
                        ) : null}
                      </View>
                    );
                  }
                  if (block.type === "tool_call") {
                    const expanded = expandedToolCallByBlockId[blockId];
                    return (
                      <View
                        key={blockId}
                        className={`${
                          blockIndex > 0 ? "mt-3" : ""
                        } rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2`}
                      >
                        <Pressable onPress={() => toggleToolCall(blockId)}>
                          <Text className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                            {expanded ? "Hide Tool Call" : "Show Tool Call"}
                          </Text>
                        </Pressable>
                        {expanded ? (
                          <Text
                            selectable
                            className="mt-1 break-all text-xs text-slate-300"
                          >
                            {blockText}
                          </Text>
                        ) : null}
                      </View>
                    );
                  }
                  if (block.type === "text") {
                    return (
                      <Text
                        key={blockId}
                        selectable
                        className={`${
                          blockIndex > 0 ? "mt-3" : ""
                        } break-all text-sm text-white`}
                      >
                        {blockText}
                      </Text>
                    );
                  }
                  return (
                    <View
                      key={blockId}
                      className={`${
                        blockIndex > 0 ? "mt-3" : ""
                      } rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2`}
                    >
                      <Text className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                        {block.type}
                      </Text>
                      <Text
                        selectable
                        className="mt-1 break-all text-xs text-slate-300"
                      >
                        {blockText}
                      </Text>
                    </View>
                  );
                })
              ) : (
                <Text selectable className="break-all text-sm text-white">
                  {message.content}
                </Text>
              )}
              {message.status === "streaming" ? (
                <Text className="mt-1 text-[10px] text-muted">
                  Streaming...
                </Text>
              ) : null}
            </Pressable>
            <View
              className={`mt-2 flex-row ${
                message.role === "user" ? "justify-start" : "justify-end"
              }`}
            >
              <Pressable
                className="rounded-lg px-2 py-2 opacity-60"
                onPress={() => handleCopyMessage(message)}
                accessibilityRole="button"
                accessibilityLabel="Copy message"
              >
                <Ionicons
                  name="copy-outline"
                  size={16}
                  color={message.role === "user" ? "#ffffff" : "#cbd5e1"}
                />
              </Pressable>
            </View>
          </View>
          {canRetry && (
            <Pressable
              onPress={handleRetry}
              className="mt-1.5 flex-row items-center gap-1 opacity-70"
            >
              <Ionicons name="refresh" size={12} color="#94a3b8" />
              <Text className="text-[10px] font-semibold text-slate-400">
                Retry
              </Text>
            </Pressable>
          )}
        </View>
      );
    },
    [
      deriveRenderableBlocks,
      expandedReasoningByBlockId,
      expandedToolCallByBlockId,
      handleCopyMessage,
      handleRetry,
      messages.length,
      session?.streamState,
      toggleReasoning,
      toggleToolCall,
    ],
  );

  const interruptActionCard = useMemo(() => {
    if (!pendingInterrupt) {
      return null;
    }
    if (pendingInterrupt.type === "permission") {
      const permission = pendingInterrupt.details.permission ?? "unknown";
      const patterns = pendingInterrupt.details.patterns ?? [];
      return (
        <View className="mt-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4">
          <Text className="text-xs font-semibold uppercase tracking-wide text-amber-300">
            Authorization Required
          </Text>
          <Text className="mt-2 text-sm text-white">
            Permission: <Text className="font-semibold">{permission}</Text>
          </Text>
          {patterns.length > 0 ? (
            <View className="mt-2 gap-1">
              {patterns.map((pattern) => (
                <Text key={pattern} className="text-xs text-amber-100">
                  • {pattern}
                </Text>
              ))}
            </View>
          ) : null}
          <View className="mt-4 flex-row flex-wrap gap-2">
            <Button
              size="sm"
              label="Allow once"
              testID="interrupt-permission-once"
              loading={interruptAction === "permission:once"}
              disabled={Boolean(interruptAction)}
              onPress={() => handlePermissionReply("once")}
            />
            <Button
              size="sm"
              label="Always allow"
              testID="interrupt-permission-always"
              variant="secondary"
              loading={interruptAction === "permission:always"}
              disabled={Boolean(interruptAction)}
              onPress={() => handlePermissionReply("always")}
            />
            <Button
              size="sm"
              label="Reject"
              testID="interrupt-permission-reject"
              variant="danger"
              loading={interruptAction === "permission:reject"}
              disabled={Boolean(interruptAction)}
              onPress={() => handlePermissionReply("reject")}
            />
          </View>
        </View>
      );
    }

    const questions = pendingInterrupt.details.questions ?? [];
    return (
      <View className="mt-3 rounded-2xl border border-sky-500/40 bg-sky-500/10 p-4">
        <Text className="text-xs font-semibold uppercase tracking-wide text-sky-300">
          Additional Input Required
        </Text>
        {questions.map((question, index) => {
          const answer = questionAnswers[index] ?? "";
          return (
            <View
              key={`${pendingInterrupt.requestId}:${index}`}
              className="mt-3"
            >
              {question.header ? (
                <Text className="text-[11px] font-semibold text-sky-200">
                  {question.header}
                </Text>
              ) : null}
              <Text className="mt-1 text-sm text-white">
                {question.question}
              </Text>
              <TextInput
                testID={`interrupt-question-input-${index}`}
                className="mt-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
                value={answer}
                editable={!interruptAction}
                placeholder="Type your answer"
                placeholderTextColor="#6b7280"
                onChangeText={(value) =>
                  handleQuestionAnswerChange(index, value)
                }
              />
              {question.options.length > 0 ? (
                <View className="mt-2 flex-row flex-wrap gap-2">
                  {question.options.map((option) => {
                    const optionValue = option.value || option.label;
                    return (
                      <Pressable
                        key={`${pendingInterrupt.requestId}:${index}:${option.label}`}
                        className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1"
                        disabled={Boolean(interruptAction)}
                        onPress={() =>
                          handleQuestionOptionPick(index, optionValue)
                        }
                      >
                        <Text className="text-[11px] text-slate-200">
                          {option.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              ) : null}
            </View>
          );
        })}
        <View className="mt-4 flex-row flex-wrap gap-2">
          <Button
            size="sm"
            label="Submit answers"
            testID="interrupt-question-submit"
            loading={interruptAction === "question:reply"}
            disabled={Boolean(interruptAction)}
            onPress={handleQuestionReply}
          />
          <Button
            size="sm"
            label="Reject"
            testID="interrupt-question-reject"
            variant="danger"
            loading={interruptAction === "question:reject"}
            disabled={Boolean(interruptAction)}
            onPress={handleQuestionReject}
          />
        </View>
      </View>
    );
  }, [
    handlePermissionReply,
    handleQuestionAnswerChange,
    handleQuestionOptionPick,
    handleQuestionReject,
    handleQuestionReply,
    interruptAction,
    pendingInterrupt,
    questionAnswers,
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
              onPress={() => {
                const nextConversationId = generateConversationId();
                blurActiveElement();
                router.replace(buildChatRoute(agent.id, nextConversationId));
              }}
              accessibilityRole="button"
              accessibilityLabel="Start new session"
              accessibilityHint="Clear the current chat session"
            >
              <Ionicons name="add" size={20} color="#ffffff" />
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

      {session?.streamState === "rebinding" ? (
        <View className="mx-6 mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2">
          <Text className="text-xs text-amber-300">
            Connection dropped. Rebinding this session...
          </Text>
        </View>
      ) : null}

      {session?.streamState === "recoverable" ? (
        <View className="mx-6 mt-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2">
          <Text className="text-xs text-emerald-300">
            Session recovered. You can continue chatting in this session.
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
        renderItem={renderChatMessage}
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
          interruptActionCard ? <View>{interruptActionCard}</View> : null
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

        {showPresets ? (
          <View className="absolute bottom-20 left-6 right-6 z-50 rounded-2xl border border-slate-800 bg-slate-900 p-2 shadow-2xl">
            <View className="max-h-64 overflow-hidden">
              <ScrollView keyboardShouldPersistTaps="handled">
                {shortcuts.map((cmd) => (
                  <View
                    key={cmd.id}
                    className="flex-row items-center justify-between rounded-xl active:bg-slate-800"
                  >
                    <Pressable
                      className="flex-1 px-4 py-3"
                      onPress={() => handleSelectPreset(cmd.value)}
                    >
                      <Text className="text-sm text-white" numberOfLines={1}>
                        {cmd.label}
                      </Text>
                    </Pressable>
                    {cmd.isCustom && (
                      <Pressable
                        className="px-4 py-3"
                        onPress={() => removeShortcut(cmd.id)}
                      >
                        <Text className="text-xs font-semibold text-red-400">
                          Del
                        </Text>
                      </Pressable>
                    )}
                  </View>
                ))}
              </ScrollView>
            </View>
            <View className="mt-2 border-t border-slate-800 pt-2">
              <Pressable
                className={`rounded-xl px-4 py-3 ${
                  input.trim() ? "bg-primary/20" : "opacity-50"
                }`}
                onPress={handleSaveShortcut}
                disabled={!input.trim()}
              >
                <Text
                  className={`text-xs font-bold ${
                    input.trim() ? "text-primary" : "text-muted"
                  }`}
                >
                  Save current input as shortcut
                </Text>
              </Pressable>
            </View>
          </View>
        ) : null}

        <View className="flex-row items-end gap-2 bg-slate-900/50 p-2 rounded-3xl border border-slate-800">
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
          <View className="flex-row items-center gap-1.5 pb-1">
            <Pressable
              className={`h-9 w-9 items-center justify-center rounded-xl ${
                showPresets ? "bg-primary" : "bg-slate-800"
              }`}
              onPress={() => setShowPresets(!showPresets)}
              accessibilityRole="button"
              accessibilityLabel="Toggle shortcuts"
            >
              <Ionicons
                name={showPresets ? "flash" : "flash-outline"}
                size={18}
                color={showPresets ? "#ffffff" : "#94a3b8"}
              />
            </Pressable>
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
      </View>
    </KeyboardAvoidingView>
  );
}
