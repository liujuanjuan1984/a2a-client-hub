import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { usePaginatedList } from "@/hooks/usePaginatedList";
import {
  continueOpencodeSession,
  listOpencodeSessionsDirectoryPage,
  type OpencodeSessionDirectoryItem,
} from "@/lib/api/opencodeSessions";
import { formatLocalDateTimeYmdHm } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/store/chat";

export function SessionsScreen() {
  const router = useRouter();

  const generateSessionId = useChatStore((state) => state.generateSessionId);
  const ensureSession = useChatStore((state) => state.ensureSession);
  const bindOpencodeSession = useChatStore(
    (state) => state.bindOpencodeSession,
  );

  const refreshNextRef = useRef(false);

  const fetchPage = useCallback(
    async (page: number) => {
      const refresh = page === 1 && refreshNextRef.current;
      if (refresh) refreshNextRef.current = false;
      const result = await listOpencodeSessionsDirectoryPage({
        page,
        size: 50,
        refresh,
      });
      return { items: result.items, nextPage: result.nextPage };
    },
    [refreshNextRef, listOpencodeSessionsDirectoryPage],
  );

  const {
    items,
    hasMore,
    loading,
    refreshing,
    loadingMore,
    reset,
    loadFirstPage,
    loadMore,
  } = usePaginatedList<OpencodeSessionDirectoryItem>({
    fetchPage,
    getKey: (item) => `${item.agent_id}:${item.session_id}`,
    errorTitle: "Load sessions failed",
    fallbackMessage: "Load failed.",
  });

  useEffect(() => {
    reset();
    loadFirstPage().catch(() => {
      // Error already handled
    });
  }, [loadFirstPage, reset]);

  const onRefresh = async () => {
    refreshNextRef.current = true;
    await loadFirstPage("refreshing");
  };

  const sortedItems = useMemo(() => items, [items]);

  const continueSession = async (item: OpencodeSessionDirectoryItem) => {
    const agentId = item.agent_id;
    const source = item.agent_source;
    const opencodeSessionId = item.session_id;
    if (!opencodeSessionId) {
      toast.error("Continue session failed", "Missing session id.");
      return;
    }
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
    }
  };

  return (
    <View className="flex-1 bg-background px-6 pt-10">
      <PageHeader
        title="Sessions"
        subtitle="Browse OpenCode sessions across all agents."
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
            <Text className="text-sm text-muted">Loading sessions...</Text>
          </View>
        ) : sortedItems.length === 0 ? (
          <View className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
            <Text className="text-base font-semibold text-white">
              No sessions
            </Text>
            <Text className="mt-2 text-sm text-muted">
              No OpenCode sessions found.
            </Text>
          </View>
        ) : (
          <>
            {sortedItems.map((item) => {
              const title = item.title;
              const sessionId = item.session_id;
              const ts = item.last_active_at ?? null;
              return (
                <View
                  key={`${item.agent_id}:${sessionId}`}
                  className="mb-3 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/30"
                >
                  <View className="p-4">
                    <Text
                      className="text-base font-semibold text-white"
                      numberOfLines={1}
                    >
                      {item.agent_name}
                    </Text>
                    <Text
                      className="mt-1 text-sm text-slate-100"
                      numberOfLines={1}
                    >
                      {title}
                    </Text>
                    <Text
                      className="mt-2 text-xs text-slate-400"
                      numberOfLines={1}
                    >
                      {sessionId}
                    </Text>
                  </View>

                  <View className="flex-row items-center justify-between gap-3 border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
                    <View className="flex-1">
                      <Text className="text-[10px] font-bold uppercase tracking-wider text-muted">
                        Last active
                      </Text>
                      <Text className="mt-1 text-xs text-slate-200">
                        {formatLocalDateTimeYmdHm(ts)}
                      </Text>
                    </View>
                    <Button
                      size="xs"
                      variant="secondary"
                      label="Continue"
                      iconRight="chevron-forward"
                      onPress={() => continueSession(item)}
                    />
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
