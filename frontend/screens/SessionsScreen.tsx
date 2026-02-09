import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { usePaginatedList } from "@/hooks/usePaginatedList";
import { A2AExtensionCallError } from "@/lib/api/a2aExtensions";
import { ApiRequestError } from "@/lib/api/client";
import {
  continueOpencodeSession,
  listOpencodeSessionsPage,
} from "@/lib/api/opencodeSessions";
import { formatLocalDateTime } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import {
  getOpencodeSessionId,
  getOpencodeSessionTimestamp,
  getOpencodeSessionTitle,
} from "@/lib/opencodeAdapters";
import {
  buildChatRoute,
  buildOpencodeSessionMessagesRoute,
} from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";

export function SessionsScreen() {
  const router = useRouter();

  const agents = useAgentStore((state) => state.agents);
  const storeActiveAgentId = useAgentStore((state) => state.activeAgentId);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const generateSessionId = useChatStore((state) => state.generateSessionId);
  const ensureSession = useChatStore((state) => state.ensureSession);
  const bindOpencodeSession = useChatStore(
    (state) => state.bindOpencodeSession,
  );

  useEffect(() => {
    if (selectedAgentId) return;
    if (storeActiveAgentId) {
      setSelectedAgentId(storeActiveAgentId);
      return;
    }
    const fallback = agents[0]?.id ?? null;
    if (fallback) setSelectedAgentId(fallback);
  }, [agents, selectedAgentId, storeActiveAgentId]);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) ?? null,
    [agents, selectedAgentId],
  );

  const source = selectedAgent?.source ?? "personal";

  const fetchPage = useCallback(
    async (page: number) => {
      if (!selectedAgentId) {
        return { items: [], nextPage: undefined };
      }
      const result = await listOpencodeSessionsPage(selectedAgentId, {
        page,
        size: 50,
        source,
      });
      return { items: result.items, nextPage: result.nextPage };
    },
    [selectedAgentId, source],
  );

  const mapErrorMessage = useCallback((error: unknown) => {
    if (error instanceof A2AExtensionCallError) {
      return error.errorCode
        ? `Extension error: ${error.errorCode}`
        : error.message;
    }
    if (error instanceof ApiRequestError && error.status === 502) {
      return "This agent does not support the OpenCode sessions extension.";
    }
    return null;
  }, []);

  const {
    items,
    hasMore,
    loading,
    refreshing,
    loadingMore,
    reset,
    loadFirstPage,
    loadMore,
  } = usePaginatedList<unknown>({
    fetchPage,
    getKey: (item) => getOpencodeSessionId(item),
    errorTitle: "Load sessions failed",
    fallbackMessage: "Load failed.",
    mapErrorMessage,
  });

  useEffect(() => {
    reset();
    if (!selectedAgentId) return;
    loadFirstPage().catch(() => {
      // Error already handled
    });
  }, [loadFirstPage, reset, selectedAgentId]);

  const onRefresh = async () => {
    if (!selectedAgentId) return;
    await loadFirstPage("refreshing");
  };

  const sortedItems = useMemo(() => {
    const copy = [...items];
    copy.sort((a, b) => {
      const aTs = getOpencodeSessionTimestamp(a) ?? "";
      const bTs = getOpencodeSessionTimestamp(b) ?? "";
      if (aTs && bTs) return bTs.localeCompare(aTs);
      if (aTs) return -1;
      if (bTs) return 1;
      return 0;
    });
    return copy;
  }, [items]);

  const openMessages = (item: unknown) => {
    if (!selectedAgentId) return;
    const sessionId = getOpencodeSessionId(item);
    if (!sessionId) {
      toast.error("Open session failed", "Missing session id.");
      return;
    }
    blurActiveElement();
    router.push(buildOpencodeSessionMessagesRoute(selectedAgentId, sessionId));
  };

  const continueSession = async (item: unknown) => {
    if (!selectedAgentId) return;
    const opencodeSessionId = getOpencodeSessionId(item);
    if (!opencodeSessionId) {
      toast.error("Continue session failed", "Missing session id.");
      return;
    }
    try {
      const binding = await continueOpencodeSession(
        selectedAgentId,
        opencodeSessionId,
        {
          source,
        },
      );
      const chatSessionId = generateSessionId();
      ensureSession(chatSessionId, selectedAgentId);
      bindOpencodeSession(chatSessionId, {
        agentId: selectedAgentId,
        opencodeSessionId,
        contextId: binding.contextId ?? undefined,
        metadata: binding.metadata,
      });
      blurActiveElement();
      router.push(
        buildChatRoute(selectedAgentId, chatSessionId, {
          opencodeSessionId,
        }),
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Continue failed.";
      toast.error("Continue session failed", message);
    }
  };

  return (
    <View className="flex-1 bg-background px-6 pt-10">
      <PageHeader
        title="Sessions"
        subtitle="Browse OpenCode sessions by agent."
      />

      {agents.length > 0 ? (
        <ScrollView
          className="mt-4"
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingRight: 12 }}
        >
          {agents.map((agent) => {
            const selected = agent.id === selectedAgentId;
            return (
              <Pressable
                key={agent.id}
                className={`mr-2 rounded-full border px-4 py-2 ${
                  selected
                    ? "border-primary bg-primary/20"
                    : "border-slate-700 bg-slate-900"
                }`}
                onPress={() => setSelectedAgentId(agent.id)}
              >
                <Text
                  className={`text-xs font-semibold ${
                    selected ? "text-primary" : "text-slate-200"
                  }`}
                  numberOfLines={1}
                >
                  {agent.name}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      ) : null}

      <ScrollView
        className="mt-4"
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        {loading ? (
          <View className="mt-8 items-center">
            <Text className="text-sm text-muted">Loading sessions...</Text>
          </View>
        ) : sortedItems.length === 0 ? (
          <View className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
            <Text className="text-base font-semibold text-white">
              No sessions
            </Text>
            <Text className="mt-2 text-sm text-muted">
              {selectedAgent
                ? "No OpenCode sessions found for this agent."
                : "Select an agent to load sessions."}
            </Text>
          </View>
        ) : (
          <>
            {sortedItems.map((item) => {
              const title = getOpencodeSessionTitle(item);
              const sessionId = getOpencodeSessionId(item);
              const ts = getOpencodeSessionTimestamp(item);
              return (
                <View
                  key={sessionId}
                  className="mb-3 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/30"
                >
                  <View className="p-4">
                    <Text
                      className="text-sm font-semibold text-white"
                      numberOfLines={1}
                    >
                      {title}
                    </Text>
                    <Text
                      className="mt-1 text-xs text-slate-400"
                      numberOfLines={1}
                    >
                      {sessionId}
                    </Text>
                    {ts ? (
                      <Text className="mt-2 text-xs text-slate-400">
                        Last active: {formatLocalDateTime(ts)}
                      </Text>
                    ) : null}
                  </View>

                  <View className="flex-row items-center justify-end gap-1 border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
                    <Pressable
                      className="flex-row items-center gap-2 rounded-lg px-3 py-2 active:bg-slate-800/40"
                      onPress={() => continueSession(item)}
                      accessibilityRole="button"
                      accessibilityLabel="Continue session in chat"
                      disabled={!selectedAgentId}
                    >
                      <Text className="text-xs font-semibold text-slate-200">
                        Continue
                      </Text>
                    </Pressable>

                    <Pressable
                      className="flex-row items-center gap-2 rounded-lg px-3 py-2 active:bg-slate-800/40"
                      onPress={() => openMessages(item)}
                      accessibilityRole="button"
                      accessibilityLabel="Open session messages"
                      disabled={!selectedAgentId}
                    >
                      <Text className="text-xs font-semibold text-slate-200">
                        Messages
                      </Text>
                      <Ionicons
                        name="chevron-forward"
                        size={14}
                        color="#94a3b8"
                      />
                    </Pressable>
                  </View>
                </View>
              );
            })}

            {hasMore ? (
              <Button
                className="mt-2 self-center"
                label={loadingMore ? "Loading..." : "Load more"}
                size="sm"
                variant="secondary"
                loading={loadingMore}
                onPress={() => loadMore()}
              />
            ) : null}
          </>
        )}
      </ScrollView>
    </View>
  );
}
