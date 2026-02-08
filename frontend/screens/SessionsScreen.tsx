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
import { ApiRequestError } from "@/lib/api/client";
import {
  listSessionsPage,
  type SessionItem,
  type SessionSource,
} from "@/lib/api/sessions";
import { formatLocalDateTime } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";

const sourceOptions: { value: "all" | SessionSource; label: string }[] = [
  { value: "all", label: "All" },
  { value: "manual", label: "Manual" },
  { value: "scheduled", label: "Scheduled" },
];

export function SessionsScreen() {
  const router = useRouter();
  const agents = useAgentStore((state) => state.agents);
  const [sourceFilter, setSourceFilter] = useState<"all" | SessionSource>(
    "all",
  );

  const agentNameMap = useMemo(() => {
    const map = new Map<string, string>();
    agents.forEach((agent) => map.set(agent.id, agent.name));
    return map;
  }, [agents]);

  const source = sourceFilter === "all" ? undefined : sourceFilter;

  const fetchSessionsPage = useCallback(
    async (page: number) => {
      const result = await listSessionsPage(source, { page });
      return { items: result.items, nextPage: result.nextPage };
    },
    [source],
  );

  const mapErrorMessage = useCallback((error: unknown) => {
    if (error instanceof ApiRequestError && error.status === 503) {
      return "A2A integration is disabled.";
    }
    return null;
  }, []);

  const {
    items: sessions,
    hasMore,
    loading,
    refreshing,
    loadingMore,
    reset,
    loadFirstPage,
    loadMore,
  } = usePaginatedList<SessionItem>({
    fetchPage: fetchSessionsPage,
    getKey: (item) => item.id,
    errorTitle: "Load sessions failed",
    fallbackMessage: "Load failed.",
    mapErrorMessage,
  });

  useEffect(() => {
    reset();
    loadFirstPage().catch(() => {
      // Error already handled in hook
    });
  }, [sourceFilter, loadFirstPage, reset]);

  const onRefresh = async () => {
    await loadFirstPage("refreshing");
  };

  const openSession = (session: SessionItem) => {
    if (!session.agent_id) {
      toast.error("Open session failed", "Missing agent id.");
      return;
    }
    blurActiveElement();
    router.push(
      buildChatRoute(session.agent_id, session.id, {
        history: true,
        source: session.source,
      }),
    );
  };

  return (
    <View className="flex-1 bg-background px-6 pt-10">
      <PageHeader
        title="Sessions"
        subtitle="Switch between manual and scheduled conversations."
      />

      <View className="mt-4 flex-row gap-2">
        {sourceOptions.map((option) => {
          const selected = sourceFilter === option.value;
          return (
            <Pressable
              key={option.value}
              className={`rounded-lg border px-3 py-1.5 ${
                selected
                  ? "border-primary bg-primary/20"
                  : "border-slate-700 bg-slate-900"
              }`}
              onPress={() => setSourceFilter(option.value)}
            >
              <Text
                className={`text-xs ${selected ? "text-primary" : "text-slate-300"}`}
              >
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

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
        ) : sessions.length === 0 ? (
          <View className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
            <Text className="text-base font-semibold text-white">
              No sessions
            </Text>
            <Text className="mt-2 text-sm text-muted">
              No sessions found for the current filter.
            </Text>
          </View>
        ) : (
          <>
            {sessions.map((session) => (
              <View
                key={session.id}
                className="mb-3 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/30"
              >
                <View className="p-4">
                  <View className="flex-row items-start justify-between">
                    <View className="flex-1 pr-3">
                      <Text
                        className="text-sm font-semibold text-white"
                        numberOfLines={1}
                      >
                        {session.title || session.id}
                      </Text>

                      <View className="mt-2 self-start flex-row items-center gap-1 rounded-full bg-slate-800/60 px-2.5 py-1">
                        <Ionicons
                          name={
                            session.source === "scheduled"
                              ? "calendar-outline"
                              : "person-outline"
                          }
                          size={12}
                          color={
                            session.source === "scheduled"
                              ? "#5c6afb"
                              : "#94a3b8"
                          }
                        />
                        <Text
                          className={`text-[11px] font-semibold ${
                            session.source === "scheduled"
                              ? "text-primary"
                              : "text-slate-300"
                          }`}
                        >
                          {session.source === "scheduled"
                            ? "Scheduled"
                            : "Manual"}
                        </Text>
                      </View>

                      <Text
                        className="mt-2 text-xs text-slate-400"
                        numberOfLines={1}
                      >
                        Agent:{" "}
                        {agentNameMap.get(session.agent_id) ?? session.agent_id}
                      </Text>
                      <Text className="mt-1 text-xs text-slate-400">
                        Last active:{" "}
                        {formatLocalDateTime(
                          session.last_active_at ?? session.created_at,
                        )}
                      </Text>
                      {session.job_id ? (
                        <Text className="mt-1 text-xs text-slate-400">
                          Job: {session.job_id}
                        </Text>
                      ) : null}
                    </View>
                  </View>
                </View>

                <View className="flex-row items-center justify-end border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
                  <Button
                    label="Open"
                    size="xs"
                    variant="secondary"
                    iconRight="chevron-forward"
                    onPress={() => openSession(session)}
                    accessibilityRole="button"
                    accessibilityLabel="Open session"
                    accessibilityHint={`Open ${session.title || session.id}`}
                  />
                </View>
              </View>
            ))}

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
