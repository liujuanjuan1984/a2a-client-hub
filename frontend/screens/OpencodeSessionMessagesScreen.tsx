import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { usePaginatedList } from "@/hooks/usePaginatedList";
import { A2AExtensionCallError } from "@/lib/api/a2aExtensions";
import { ApiRequestError } from "@/lib/api/client";
import { listOpencodeSessionMessagesPage } from "@/lib/api/opencodeSessions";
import { formatLocalDateTime } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import {
  getOpencodeMessageId,
  getOpencodeMessageRole,
  getOpencodeMessageText,
  getOpencodeMessageTimestamp,
} from "@/lib/opencodeAdapters";
import { useAgentStore } from "@/store/agents";

export function OpencodeSessionMessagesScreen({
  agentId,
  sessionId,
}: {
  agentId: string;
  sessionId: string;
}) {
  const router = useRouter();
  const agents = useAgentStore((state) => state.agents);
  const agent = useMemo(
    () => agents.find((item) => item.id === agentId),
    [agents, agentId],
  );
  const source = agent?.source ?? "personal";

  const fetchPage = useCallback(
    async (page: number) => {
      const result = await listOpencodeSessionMessagesPage(agentId, sessionId, {
        page,
        source,
      });
      return { items: result.items, nextPage: result.nextPage };
    },
    [agentId, sessionId, source],
  );

  const mapErrorMessage = useCallback((error: unknown) => {
    if (error instanceof A2AExtensionCallError) {
      if (error.errorCode === "session_not_found") {
        return "Session not found.";
      }
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
    getKey: (item) => getOpencodeMessageId(item),
    errorTitle: "Load messages failed",
    fallbackMessage: "Load failed.",
    mapErrorMessage,
  });

  useEffect(() => {
    reset();
    loadFirstPage().catch(() => {
      // Error already handled
    });
  }, [agentId, sessionId, loadFirstPage, reset]);

  const onRefresh = async () => {
    await loadFirstPage("refreshing");
  };

  const subtitle = agent?.name
    ? `${agent.name} • ${sessionId}`
    : `Agent: ${agentId} • ${sessionId}`;

  return (
    <View className="flex-1 bg-background px-6 pt-10">
      <PageHeader
        title="OpenCode Messages"
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

      <ScrollView
        className="mt-4"
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        {loading ? (
          <View className="mt-8 items-center">
            <Text className="text-sm text-muted">Loading messages...</Text>
          </View>
        ) : items.length === 0 ? (
          <View className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
            <Text className="text-base font-semibold text-white">
              No messages
            </Text>
            <Text className="mt-2 text-sm text-muted">
              No messages found for this session.
            </Text>
          </View>
        ) : (
          <>
            {items.map((item) => {
              const role = getOpencodeMessageRole(item);
              const text = getOpencodeMessageText(item);
              const ts = getOpencodeMessageTimestamp(item);
              return (
                <View
                  key={getOpencodeMessageId(item)}
                  className="mb-3 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/30"
                >
                  <View className="p-4">
                    <View className="flex-row items-center justify-between">
                      <View className="flex-row items-center gap-2">
                        <Ionicons
                          name="chatbubble-ellipses-outline"
                          size={14}
                          color="#94a3b8"
                        />
                        <Text className="text-xs font-semibold text-slate-200">
                          {role}
                        </Text>
                      </View>
                      {ts ? (
                        <Text className="text-[11px] text-slate-400">
                          {formatLocalDateTime(ts)}
                        </Text>
                      ) : null}
                    </View>
                    <Text className="mt-2 text-sm text-slate-100">{text}</Text>
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
