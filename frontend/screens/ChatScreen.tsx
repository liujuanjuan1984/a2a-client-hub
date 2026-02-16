import { Ionicons } from "@expo/vector-icons";
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
import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { useSessionHistoryQuery } from "@/hooks/useChatHistoryQuery";
import { type ChatMessage, type MessageBlock } from "@/lib/api/chat-utils";
import { continueSession } from "@/lib/api/sessions";
import { blurActiveElement } from "@/lib/focus";
import { backOrHome } from "@/lib/navigation";
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
const LIST_BOTTOM_STICK_THRESHOLD = 72;
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
  const goBackOrHome = useCallback(() => backOrHome(router), [router]);
  const storeActiveAgentId = useAgentStore((state) => state.activeAgentId);
  const activeAgentId = routeAgentId || storeActiveAgentId;

  const { data: agents = [], isFetched: hasFetchedAgents } =
    useAgentsCatalogQuery(true);
  const agent = useMemo(
    () => agents.find((item) => item.id === activeAgentId),
    [agents, activeAgentId],
  );
  const ensureSession = useChatStore((state) => state.ensureSession);
  const generateConversationId = useChatStore(
    (state) => state.generateConversationId,
  );
  const sendMessage = useChatStore((state) => state.sendMessage);
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
    scheduleStickToBottom(true);
  }, [messages.length, scheduleStickToBottom]);

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
      scheduleStickToBottom(false);
    },
    [scheduleStickToBottom],
  );

  const handleListScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const offsetY = event.nativeEvent.contentOffset?.y ?? 0;
      const viewportHeight = event.nativeEvent.layoutMeasurement?.height ?? 0;
      const contentHeight = event.nativeEvent.contentSize?.height ?? 0;
      const distanceToBottom = contentHeight - (offsetY + viewportHeight);
      shouldStickToBottomRef.current =
        distanceToBottom <= LIST_BOTTOM_STICK_THRESHOLD;
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
  const statusColor = useMemo(() => {
    if (agent?.status === "success") return "bg-emerald-500";
    if (agent?.status === "error") return "bg-red-500";
    if (agent?.status === "checking") return "bg-amber-500";
    return "bg-slate-500";
  }, [agent?.status]);
  const statusLabel = useMemo(() => {
    if (!agent) return "Idle";
    if (agent.status === "success") return "Connected";
    if (agent.status === "error") return "Failed";
    if (agent.status === "checking") return "Checking";
    return "Idle";
  }, [agent]);

  const handleSend = () => {
    if (!activeAgentId || !conversationId || !agent) {
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

  const renderChatMessage = useCallback(
    ({ item: message }: { item: ChatMessage }) => {
      const renderableBlocks = deriveRenderableBlocks(message);
      const hasBlocks = message.role === "agent" && renderableBlocks.length > 0;

      return (
        <View
          className={`mb-3 flex ${
            message.role === "user" ? "items-end" : "items-start"
          }`}
        >
          <View
            className={`max-w-[85%] rounded-2xl px-4 py-3 ${
              message.role === "user"
                ? "bg-primary"
                : message.role === "agent"
                  ? "bg-slate-800"
                  : "bg-slate-900"
            }`}
          >
            {hasBlocks ? (
              renderableBlocks.map((block, index) => {
                const blockText = block.content;
                if (blockText.length === 0) return null;
                const blockId = block.id || `${message.id}:${index}`;
                if (block.type === "reasoning") {
                  const expanded = Boolean(expandedReasoningByBlockId[blockId]);
                  return (
                    <View
                      key={blockId}
                      className={`${index > 0 ? "mt-3" : ""} rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2`}
                    >
                      <Pressable onPress={() => toggleReasoning(blockId)}>
                        <Text className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                          {expanded ? "Hide Reasoning" : "Show Reasoning"}
                        </Text>
                      </Pressable>
                      {expanded ? (
                        <Text className="mt-1 break-all text-xs text-slate-300">
                          {blockText}
                        </Text>
                      ) : null}
                    </View>
                  );
                }
                if (block.type === "tool_call") {
                  const expanded = Boolean(expandedToolCallByBlockId[blockId]);
                  return (
                    <View
                      key={blockId}
                      className={`${index > 0 ? "mt-3" : ""} rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2`}
                    >
                      <Pressable onPress={() => toggleToolCall(blockId)}>
                        <Text className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                          {expanded ? "Hide Tool Call" : "Show Tool Call"}
                        </Text>
                      </Pressable>
                      {expanded ? (
                        <Text className="mt-1 break-all text-xs text-slate-300">
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
                      className={`${index > 0 ? "mt-3" : ""} break-all text-sm text-white`}
                    >
                      {blockText}
                    </Text>
                  );
                }
                return (
                  <View
                    key={blockId}
                    className={`${index > 0 ? "mt-3" : ""} rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2`}
                  >
                    <Text className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                      {block.type}
                    </Text>
                    <Text className="mt-1 break-all text-xs text-slate-300">
                      {blockText}
                    </Text>
                  </View>
                );
              })
            ) : (
              <Text className="break-all text-sm text-white">
                {message.content}
              </Text>
            )}
            {message.status === "streaming" ? (
              <Text className="mt-1 text-[10px] text-muted">Streaming...</Text>
            ) : null}
          </View>
        </View>
      );
    },
    [
      deriveRenderableBlocks,
      expandedReasoningByBlockId,
      expandedToolCallByBlockId,
    ],
  );

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
            <View className={`h-2 w-2 rounded-full ${statusColor}`} />
            <View>
              <Text className="text-lg font-bold text-white" numberOfLines={1}>
                {agent.name}
              </Text>
            </View>
          </View>
          <View className="flex-row items-center gap-3">
            <Pressable
              className="h-10 w-10 items-center justify-center rounded-full bg-slate-800/50"
              onPress={goBackOrHome}
              accessibilityRole="button"
              accessibilityLabel="Go back"
              accessibilityHint="Return to the previous screen"
            >
              <Ionicons name="arrow-back" size={18} color="#ffffff" />
            </Pressable>
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
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Status
                </Text>
                <Text className="mt-1 text-xs text-white">{statusLabel}</Text>
              </View>
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
              {session?.conversationId ? (
                <View className="flex-1 min-w-[45%]">
                  <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                    Conversation ID
                  </Text>
                  <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                    {session.conversationId}
                  </Text>
                </View>
              ) : null}
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
      />

      <View className="relative border-t border-slate-800 px-6 py-4">
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

        <View className="flex-row items-end gap-3">
          <Pressable
            className={`rounded-2xl p-3 ${
              showPresets ? "bg-primary" : "bg-slate-800"
            }`}
            onPress={() => setShowPresets(!showPresets)}
            accessibilityRole="button"
            accessibilityLabel="Toggle shortcuts"
            accessibilityHint="Show quick commands"
          >
            <Text
              className={`text-[10px] font-bold ${
                showPresets ? "text-white" : "text-slate-400"
              }`}
            >
              Cmd
            </Text>
          </Pressable>
          <TextInput
            ref={inputRef}
            className="flex-1 rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3 text-white"
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
          <Button label="Send" onPress={handleSend} disabled={!input.trim()} />
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}
