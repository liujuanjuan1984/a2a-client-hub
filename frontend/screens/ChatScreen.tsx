import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import {
  continueOpencodeSession,
  listOpencodeSessionMessagesPage,
} from "@/lib/api/opencodeSessions";
import { listSessionMessagesPage } from "@/lib/api/sessions";
import { blurActiveElement } from "@/lib/focus";
import { generateId } from "@/lib/id";
import { backOrHome } from "@/lib/navigation";
import { mapOpencodeMessagesToChatMessages } from "@/lib/opencodeChatAdapters";
import { buildChatRoute } from "@/lib/routes";
import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";
import {
  buildProcessStates,
  sanitizeStreamRecords,
} from "@/lib/streamChunkView";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useMessageStore } from "@/store/messages";
import { useShortcutStore } from "@/store/shortcuts";

export function ChatScreen({
  agentId: routeAgentId,
  sessionId,
  history,
  source,
  opencodeSessionId,
}: {
  agentId?: string;
  sessionId?: string;
  history?: boolean;
  source?: "manual" | "scheduled";
  opencodeSessionId?: string;
}) {
  const router = useRouter();
  const goBackOrHome = useCallback(() => backOrHome(router), [router]);
  const storeActiveAgentId = useAgentStore((state) => state.activeAgentId);
  const activeAgentId = routeAgentId || storeActiveAgentId;

  const hasLoaded = useAgentStore((state) => state.hasLoaded);
  const agent = useAgentStore((state) =>
    state.agents.find((item) => item.id === activeAgentId),
  );
  const ensureSession = useChatStore((state) => state.ensureSession);
  const sendMessage = useChatStore((state) => state.sendMessage);
  const session = useChatStore((state) =>
    sessionId ? state.sessions[sessionId] : undefined,
  );
  const setMessages = useMessageStore((state) => state.setMessages);
  const messages = useMessageStore((state) =>
    sessionId ? (state.messages[sessionId] ?? []) : [],
  );
  const { shortcuts, addShortcut, removeShortcut } = useShortcutStore();

  const [input, setInput] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyLoadingMore, setHistoryLoadingMore] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyNextPage, setHistoryNextPage] = useState<number | null>(null);
  const hasLoadedHistoryRef = useRef(false);
  const [opencodeHistoryLoading, setOpencodeHistoryLoading] = useState(false);
  const [opencodeHistoryLoadingMore, setOpencodeHistoryLoadingMore] =
    useState(false);
  const [opencodeHistoryError, setOpencodeHistoryError] = useState<
    string | null
  >(null);
  const [opencodeHistoryNextPage, setOpencodeHistoryNextPage] = useState<
    number | null
  >(null);
  const hasLoadedOpencodeHistoryRef = useRef(false);
  const suppressAutoScrollRef = useRef(false);
  const [showDetails, setShowDetails] = useState(false);
  const [showPresets, setShowPresets] = useState(false);
  const [expandedChunkMessageIds, setExpandedChunkMessageIds] = useState<
    Record<string, boolean>
  >({});
  const [detailsModeByMessageId, setDetailsModeByMessageId] = useState<
    Record<string, "raw" | "process">
  >({});
  const scrollRef = useRef<ScrollView>(null);
  const inputRef = useRef<TextInput>(null);
  const minInputHeight = 44;
  const maxInputHeight = 128;
  const [inputHeight, setInputHeight] = useState(minInputHeight);

  useEffect(() => {
    if (activeAgentId && sessionId) {
      ensureSession(sessionId, activeAgentId);
    }
  }, [activeAgentId, sessionId, ensureSession]);

  useEffect(() => {
    hasLoadedHistoryRef.current = false;
    setHistoryNextPage(null);
    setHistoryError(null);
  }, [sessionId]);

  useEffect(() => {
    hasLoadedOpencodeHistoryRef.current = false;
    setOpencodeHistoryNextPage(null);
    setOpencodeHistoryError(null);
  }, [sessionId, opencodeSessionId]);

  useEffect(() => {
    if (!history || !sessionId) return;
    if (hasLoadedHistoryRef.current) return;
    if (messages.length > 0) {
      hasLoadedHistoryRef.current = true;
      return;
    }

    let cancelled = false;
    setHistoryError(null);
    setHistoryLoading(true);

    listSessionMessagesPage(sessionId, { page: 1, size: 100 })
      .then((result) => {
        if (cancelled) return;
        const mapped = mapSessionMessagesToChatMessages(
          result.items,
          sessionId,
        ).slice(-100);
        setMessages(sessionId, mapped);
        setHistoryNextPage(
          typeof result.nextPage === "number" ? result.nextPage : null,
        );
        hasLoadedHistoryRef.current = true;
      })
      .catch((error) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Load failed.";
        setHistoryError(message);
        toast.error("Load history failed", message);
      })
      .finally(() => {
        if (cancelled) return;
        setHistoryLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [history, sessionId, messages.length, setMessages]);

  const resolveOpencodeSource = useCallback(() => {
    if (agent?.source === "shared") return "shared";
    return "personal";
  }, [agent?.source]);

  useEffect(() => {
    if (!opencodeSessionId || !sessionId || !activeAgentId) return;

    const current = useChatStore.getState().sessions[sessionId];
    if (
      current?.opencodeSessionId === opencodeSessionId &&
      ((typeof current.contextId === "string" && current.contextId.trim()) ||
        Object.keys(current.metadata ?? {}).length > 0)
    ) {
      return;
    }

    let cancelled = false;
    continueOpencodeSession(activeAgentId, opencodeSessionId, {
      source: resolveOpencodeSource(),
    })
      .then((binding) => {
        if (cancelled) return;
        useChatStore.getState().bindOpencodeSession(sessionId, {
          agentId: activeAgentId,
          opencodeSessionId,
          contextId: binding.contextId ?? undefined,
          metadata: binding.metadata,
        });
      })
      .catch((error) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Bind failed.";
        toast.error("Continue session failed", message);
      });

    return () => {
      cancelled = true;
    };
  }, [activeAgentId, opencodeSessionId, resolveOpencodeSource, sessionId]);

  useEffect(() => {
    if (!opencodeSessionId || !sessionId || !activeAgentId) return;
    if (hasLoadedOpencodeHistoryRef.current) return;
    if (messages.length > 0) {
      hasLoadedOpencodeHistoryRef.current = true;
      return;
    }

    let cancelled = false;
    setOpencodeHistoryError(null);
    setOpencodeHistoryLoading(true);

    listOpencodeSessionMessagesPage(activeAgentId, opencodeSessionId, {
      page: 1,
      size: 100,
      source: resolveOpencodeSource(),
    })
      .then((result) => {
        if (cancelled) return;
        const mapped = mapOpencodeMessagesToChatMessages(result.items).slice(
          -100,
        );
        setMessages(sessionId, mapped);
        setOpencodeHistoryNextPage(
          typeof result.nextPage === "number" ? result.nextPage : null,
        );
        hasLoadedOpencodeHistoryRef.current = true;
      })
      .catch((error) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Load failed.";
        setOpencodeHistoryError(message);
        toast.error("Load history failed", message);
      })
      .finally(() => {
        if (cancelled) return;
        setOpencodeHistoryLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    activeAgentId,
    messages.length,
    opencodeSessionId,
    resolveOpencodeSource,
    sessionId,
    setMessages,
  ]);

  const loadEarlierHistory = async () => {
    if (!history || !sessionId) return;
    if (typeof historyNextPage !== "number") return;
    if (historyLoadingMore) return;
    setHistoryLoadingMore(true);
    try {
      const result = await listSessionMessagesPage(sessionId, {
        page: historyNextPage,
        size: 100,
      });
      const mapped = mapSessionMessagesToChatMessages(result.items, sessionId);
      const merged = new Map<string, (typeof messages)[number]>();
      [...mapped, ...messages].forEach((message) => {
        merged.set(message.id, message);
      });
      const nextMessages = Array.from(merged.values())
        .sort((a, b) => a.createdAt.localeCompare(b.createdAt))
        .slice(-500);
      suppressAutoScrollRef.current = true;
      setMessages(sessionId, nextMessages);
      setHistoryNextPage(
        typeof result.nextPage === "number" ? result.nextPage : null,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Load failed.";
      toast.error("Load history failed", message);
    } finally {
      setHistoryLoadingMore(false);
    }
  };

  const loadEarlierOpencodeHistory = async () => {
    if (!opencodeSessionId || !sessionId || !activeAgentId) return;
    if (typeof opencodeHistoryNextPage !== "number") return;
    if (opencodeHistoryLoadingMore) return;
    setOpencodeHistoryLoadingMore(true);
    try {
      const result = await listOpencodeSessionMessagesPage(
        activeAgentId,
        opencodeSessionId,
        {
          page: opencodeHistoryNextPage,
          size: 100,
          source: resolveOpencodeSource(),
        },
      );
      const mapped = mapOpencodeMessagesToChatMessages(result.items);
      const merged = new Map<string, (typeof messages)[number]>();
      [...mapped, ...messages].forEach((message) => {
        merged.set(message.id, message);
      });
      const nextMessages = Array.from(merged.values())
        .sort((a, b) => a.createdAt.localeCompare(b.createdAt))
        .slice(-500);
      suppressAutoScrollRef.current = true;
      setMessages(sessionId, nextMessages);
      setOpencodeHistoryNextPage(
        typeof result.nextPage === "number" ? result.nextPage : null,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Load failed.";
      toast.error("Load history failed", message);
    } finally {
      setOpencodeHistoryLoadingMore(false);
    }
  };

  useEffect(() => {
    if (hasLoaded && !agent) {
      // Redirect: the agent is missing, so we should not keep this screen in history.
      router.replace("/");
    }
  }, [agent, hasLoaded, router]);

  useEffect(() => {
    if (suppressAutoScrollRef.current) {
      suppressAutoScrollRef.current = false;
      return;
    }
    scrollRef.current?.scrollToEnd({ animated: true });
  }, [messages.length]);

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
    if (!activeAgentId || !sessionId) {
      return;
    }
    if (!input.trim()) {
      return;
    }
    sendMessage(sessionId, activeAgentId, input);
    setInput("");
    setInputHeight(minInputHeight);
  };

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

  const handleKeyPress = (e: any) => {
    if (
      Platform.OS === "web" &&
      e.nativeEvent.key === "Enter" &&
      !e.nativeEvent.shiftKey &&
      !e.nativeEvent.isComposing
    ) {
      e.preventDefault();
      handleSend();
    }
  };

  const toggleChunkPanel = (messageId: string) => {
    setExpandedChunkMessageIds((prev) => {
      const expanded = !(prev[messageId] ?? false);
      if (!expanded) {
        setDetailsModeByMessageId((current) => ({
          ...current,
          [messageId]: "raw",
        }));
      }
      return {
        ...prev,
        [messageId]: expanded,
      };
    });
  };

  const toggleDetailsMode = (messageId: string) => {
    setDetailsModeByMessageId((prev) => ({
      ...prev,
      [messageId]: (prev[messageId] ?? "raw") === "raw" ? "process" : "raw",
    }));
  };

  if (!agent) {
    if (!hasLoaded) {
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
      <View className="border-b border-slate-800 bg-background/80 px-6 pt-12 pb-4">
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
                const nextSessionId = generateId("sess");
                blurActiveElement();
                router.replace(buildChatRoute(agent.id, nextSessionId));
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
                  Session ID
                </Text>
                <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                  {sessionId ?? "N/A"}
                </Text>
              </View>
              <View className="flex-1 min-w-[45%]">
                <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Source
                </Text>
                <Text className="mt-1 text-xs text-white">
                  {source ?? "N/A"}
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
              {session?.opencodeSessionId ? (
                <View className="flex-1 min-w-[45%]">
                  <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                    OpenCode Session
                  </Text>
                  <Text className="mt-1 text-xs text-white" numberOfLines={1}>
                    {session.opencodeSessionId}
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

            {session?.opencodeSessionId ? (
              <>
                <View className="h-[1px] bg-slate-800" />
                <Text className="text-xs text-muted">
                  OpenCode history is shown inline in this chat.
                </Text>
              </>
            ) : null}
          </View>
        ) : null}
      </View>

      <ScrollView
        ref={scrollRef}
        className="mt-2 flex-1 px-6"
        contentContainerStyle={{ paddingBottom: 24 }}
      >
        {history && typeof historyNextPage === "number" ? (
          <View className="items-center">
            <Button
              className="mt-2"
              label={historyLoadingMore ? "Loading..." : "Load earlier"}
              size="sm"
              variant="secondary"
              loading={historyLoadingMore}
              onPress={loadEarlierHistory}
            />
          </View>
        ) : null}

        {opencodeSessionId && typeof opencodeHistoryNextPage === "number" ? (
          <View className="items-center">
            <Button
              className="mt-2"
              label={opencodeHistoryLoadingMore ? "Loading..." : "Load earlier"}
              size="sm"
              variant="secondary"
              loading={opencodeHistoryLoadingMore}
              onPress={loadEarlierOpencodeHistory}
            />
          </View>
        ) : null}

        {messages?.length ? (
          messages.map((message) => {
            const streamChunks = message.streamChunks ?? [];
            const hasStreamChunks =
              message.role === "agent" && streamChunks.length > 0;
            const isChunkPanelExpanded =
              expandedChunkMessageIds[message.id] ?? false;
            const detailsMode = detailsModeByMessageId[message.id] ?? "raw";
            const sanitizedRecords = sanitizeStreamRecords(
              streamChunks,
              message.content,
            );
            const processStates = buildProcessStates(sanitizedRecords);

            return (
              <View
                key={message.id}
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
                  <Text className="break-all text-sm text-white">
                    {message.content}
                  </Text>
                  {message.status === "streaming" ? (
                    <Text className="mt-1 text-[10px] text-muted">
                      Streaming...
                    </Text>
                  ) : null}
                  {hasStreamChunks ? (
                    <View className="mt-2">
                      <Pressable
                        className="self-start rounded-md border border-slate-600 px-2 py-1"
                        onPress={() => toggleChunkPanel(message.id)}
                      >
                        <Text className="text-[10px] font-semibold text-slate-300">
                          {isChunkPanelExpanded
                            ? "Hide Details"
                            : `Show Details (${streamChunks.length})`}
                        </Text>
                      </Pressable>
                      {isChunkPanelExpanded ? (
                        <View className="mt-2 rounded-xl border border-slate-700 bg-slate-900/80 p-2">
                          <Pressable
                            className="mb-2 self-start rounded-md border border-slate-600 px-2 py-1"
                            onPress={() => toggleDetailsMode(message.id)}
                          >
                            <Text className="text-[10px] font-semibold text-slate-300">
                              {detailsMode === "raw"
                                ? "Process View"
                                : "Raw Frames"}
                            </Text>
                          </Pressable>
                          <ScrollView className="max-h-48" nestedScrollEnabled>
                            {detailsMode === "raw"
                              ? sanitizedRecords.map((record, index) => (
                                  <View
                                    key={`${message.id}-raw-${index}`}
                                    className={index > 0 ? "mt-2" : ""}
                                  >
                                    <Text className="break-all text-xs text-slate-200">
                                      {record.text}
                                    </Text>
                                  </View>
                                ))
                              : processStates.map((state, index) => (
                                  <View
                                    key={`${message.id}-proc-${index}`}
                                    className={
                                      index > 0
                                        ? "mt-2 border-t border-slate-700 pt-2"
                                        : ""
                                    }
                                  >
                                    <Text className="break-all text-xs text-slate-200">
                                      {state}
                                    </Text>
                                  </View>
                                ))}
                          </ScrollView>
                        </View>
                      ) : null}
                    </View>
                  ) : null}
                </View>
              </View>
            );
          })
        ) : (
          <View className="mt-12 items-center">
            <Text className="text-sm text-muted">
              {historyLoading || opencodeHistoryLoading
                ? "Loading history..."
                : historyError || opencodeHistoryError
                  ? historyError || opencodeHistoryError
                  : "No messages yet."}
            </Text>
          </View>
        )}
      </ScrollView>

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
