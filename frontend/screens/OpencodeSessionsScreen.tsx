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
import { validateAgentCard } from "@/lib/api/a2aAgents";
import { A2AExtensionCallError } from "@/lib/api/a2aExtensions";
import { ApiRequestError } from "@/lib/api/client";
import { validateHubAgentCard } from "@/lib/api/hubA2aAgentsUser";
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
import { supportsOpencodeSessionQuery } from "@/lib/opencodeSupport";
import {
  buildChatRoute,
  buildOpencodeSessionMessagesRoute,
} from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";

type SupportState = "checking" | "supported" | "unsupported" | "unknown";

export function OpencodeSessionsScreen({ agentId }: { agentId: string }) {
  const router = useRouter();
  const agents = useAgentStore((state) => state.agents);
  const agent = useMemo(
    () => agents.find((item) => item.id === agentId),
    [agents, agentId],
  );

  const [supportState, setSupportState] = useState<SupportState>("checking");
  const [supportMessage, setSupportMessage] = useState<string | null>(null);
  const [continuingSessionId, setContinuingSessionId] = useState<string | null>(
    null,
  );
  const source = agent?.source ?? "personal";
  const generateSessionId = useChatStore((state) => state.generateSessionId);
  const ensureSession = useChatStore((state) => state.ensureSession);
  const bindOpencodeSession = useChatStore(
    (state) => state.bindOpencodeSession,
  );

  const checkSupport = useCallback(async () => {
    setSupportState("checking");
    setSupportMessage(null);
    try {
      const response =
        source === "shared"
          ? await validateHubAgentCard(agentId)
          : await validateAgentCard(agentId);
      if (!response.success) {
        const raw = response.validation_errors?.[0] || response.message;
        const message =
          typeof raw === "string" && raw.trim()
            ? raw
            : "Could not validate agent card.";
        setSupportState("unknown");
        setSupportMessage(message);
        return;
      }
      const supported = supportsOpencodeSessionQuery(response.card);
      setSupportState(supported ? "supported" : "unsupported");
      setSupportMessage(
        supported
          ? null
          : "This agent does not advertise the OpenCode session query extension.",
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Check failed.";
      setSupportState("unknown");
      setSupportMessage(message);
    }
  }, [agentId, source]);

  useEffect(() => {
    checkSupport().catch(() => {
      // Error already handled
    });
  }, [checkSupport]);

  const fetchPage = useCallback(
    async (page: number) => {
      const result = await listOpencodeSessionsPage(agentId, {
        page,
        source,
      });
      return { items: result.items, nextPage: result.nextPage };
    },
    [agentId, source],
  );

  const mapErrorMessage = useCallback((error: unknown) => {
    if (error instanceof A2AExtensionCallError) {
      if (error.errorCode === "upstream_unreachable") {
        return "Upstream is unreachable.";
      }
      if (error.errorCode === "upstream_http_error") {
        return "Upstream returned an HTTP error.";
      }
      return error.errorCode
        ? `Extension error: ${error.errorCode}`
        : error.message;
    }
    if (error instanceof ApiRequestError && error.status === 502) {
      return "Extension is not supported or the contract is invalid.";
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
    errorTitle: "Load OpenCode sessions failed",
    fallbackMessage: "Load failed.",
    mapErrorMessage,
  });

  useEffect(() => {
    reset();
    if (supportState !== "supported") {
      return;
    }
    loadFirstPage().catch(() => {
      // Error already handled
    });
  }, [agentId, loadFirstPage, reset, supportState]);

  const onRefresh = async () => {
    if (supportState !== "supported") return;
    await loadFirstPage("refreshing");
  };

  const openSession = (item: unknown) => {
    const sessionId = getOpencodeSessionId(item);
    if (!sessionId) {
      toast.error("Open session failed", "Missing session id.");
      return;
    }
    blurActiveElement();
    router.push(buildOpencodeSessionMessagesRoute(agentId, sessionId));
  };

  const continueSession = async (item: unknown) => {
    const opencodeSessionId = getOpencodeSessionId(item);
    if (!opencodeSessionId) {
      toast.error("Continue session failed", "Missing session id.");
      return;
    }
    setContinuingSessionId(opencodeSessionId);
    try {
      const binding = await continueOpencodeSession(
        agentId,
        opencodeSessionId,
        {
          source,
        },
      );

      const chatSessionId = generateSessionId();
      ensureSession(chatSessionId, agentId);
      bindOpencodeSession(chatSessionId, {
        agentId,
        opencodeSessionId,
        contextId: binding.contextId ?? undefined,
        metadata: binding.metadata,
      });
      blurActiveElement();
      router.push(
        buildChatRoute(agentId, chatSessionId, {
          opencodeSessionId,
        }),
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Continue failed.";
      toast.error("Continue session failed", message);
    } finally {
      setContinuingSessionId(null);
    }
  };

  const subtitle = agent?.name ? `Agent: ${agent.name}` : `Agent: ${agentId}`;

  return (
    <View className="flex-1 bg-background px-6 pt-10">
      <PageHeader
        title="OpenCode Sessions"
        subtitle={subtitle}
        rightElement={
          <Button
            label="Back"
            size="xs"
            variant="secondary"
            iconLeft="chevron-back"
            onPress={() => {
              blurActiveElement();
              if (router.canGoBack()) {
                router.back();
              } else {
                router.replace("/");
              }
            }}
          />
        }
      />

      {supportState === "checking" ? (
        <View className="mt-4 flex-row items-center gap-2">
          <Ionicons name="pulse-outline" size={16} color="#94a3b8" />
          <Text className="text-sm text-muted">
            Checking extension support...
          </Text>
        </View>
      ) : supportState === "unsupported" ? (
        <View className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
          <Text className="text-base font-semibold text-white">
            Extension not supported
          </Text>
          <Text className="mt-2 text-sm text-muted">
            {supportMessage ??
              "This agent does not support the OpenCode session query extension."}
          </Text>
          <Button
            className="mt-5 self-start"
            label="Re-check"
            size="sm"
            variant="secondary"
            onPress={() => checkSupport()}
          />
        </View>
      ) : supportMessage ? (
        <View className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/30 p-4">
          <Text className="text-sm text-muted">{supportMessage}</Text>
          <Button
            className="mt-3 self-start"
            label="Re-check"
            size="xs"
            variant="secondary"
            onPress={() => checkSupport()}
          />
        </View>
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
        ) : items.length === 0 ? (
          <View className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
            <Text className="text-base font-semibold text-white">
              No sessions
            </Text>
            <Text className="mt-2 text-sm text-muted">
              No sessions found for this agent.
            </Text>
          </View>
        ) : (
          <>
            {items.map((item) => {
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
                        Updated: {formatLocalDateTime(ts)}
                      </Text>
                    ) : null}
                  </View>

                  <View className="flex-row items-center justify-end gap-1 border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
                    <Pressable
                      className="flex-row items-center gap-2 rounded-lg px-3 py-2 active:bg-slate-800/40"
                      onPress={() => continueSession(item)}
                      accessibilityRole="button"
                      accessibilityLabel="Continue session in chat"
                      disabled={continuingSessionId === sessionId}
                    >
                      <Text className="text-xs font-semibold text-slate-200">
                        {continuingSessionId === sessionId
                          ? "Continuing..."
                          : "Continue"}
                      </Text>
                    </Pressable>

                    <Pressable
                      className="flex-row items-center gap-2 rounded-lg px-3 py-2 active:bg-slate-800/40"
                      onPress={() => openSession(item)}
                      accessibilityRole="button"
                      accessibilityLabel="Open session messages"
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
