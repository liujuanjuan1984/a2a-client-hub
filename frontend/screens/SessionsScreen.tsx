import { useMemo, useCallback } from "react";
import { RefreshControl, FlatList, Text, View } from "react-native";

import { AccountEntryButton } from "@/components/auth/AccountEntryButton";
import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { useContinueSession } from "@/hooks/useContinueSession";
import { useSessionsDirectoryQuery } from "@/hooks/useSessionsDirectoryQuery";
import { type SessionListItem } from "@/lib/api/sessions";
import {
  getSessionTimelineText,
  resolveSessionAgentPresentation,
} from "@/lib/sessionDirectoryPresentation";

export function SessionsScreen() {
  const { continueSession } = useContinueSession();
  const { data: agents = [] } = useAgentsCatalogQuery(true);

  const {
    items,
    hasMore,
    loading,
    refreshing,
    loadingMore,
    refresh,
    loadMore,
  } = useSessionsDirectoryQuery();

  const sortedItems = useMemo(() => items, [items]);
  const agentLookup = useMemo(
    () =>
      new Map(
        agents.map((agent) => [
          agent.id,
          { name: agent.name, source: agent.source },
        ]),
      ),
    [agents],
  );

  const handleContinueSession = async (item: SessionListItem) => {
    if (!item.agent_id) return;
    await continueSession({
      agentId: item.agent_id,
      conversationId: item.conversationId,
      createdAt: item.created_at ?? null,
      lastActiveAt: item.last_active_at ?? item.created_at ?? null,
    });
  };

  const renderSessionItem = useCallback(
    ({ item }: { item: SessionListItem }) => {
      const agent = resolveSessionAgentPresentation(item, agentLookup);
      const timeline = getSessionTimelineText(item);
      return (
        <View
          key={item.conversationId}
          className="mb-4 rounded-2xl bg-surface overflow-hidden shadow-sm"
        >
          <View className="px-4 py-4 pb-3.5">
            <View className="flex-row items-center justify-between mb-1.5">
              <Text
                className="text-[10px] font-semibold uppercase tracking-widest text-neo-green"
                numberOfLines={1}
              >
                {agent.name}
              </Text>
              <Text className="text-[10px] font-bold text-slate-700 uppercase">
                {item.source}
              </Text>
            </View>
            <Text
              className="text-[13px] font-semibold text-white/90"
              numberOfLines={2}
            >
              {item.title}
            </Text>
          </View>

          <View className="flex-row items-center justify-between gap-2 bg-black/20 px-4 py-2.5">
            <View className="flex-1">
              <Text className="text-[10px] font-medium text-slate-500">
                {timeline.timelineRangeText}
              </Text>
            </View>
            <View className="flex-row items-center">
              <Button
                label="Open"
                size="sm"
                variant="primary"
                iconRight="chevron-forward"
                disabled={!item.agent_id}
                onPress={() => handleContinueSession(item)}
                accessibilityRole="button"
                accessibilityLabel="Open session"
              />
            </View>
          </View>
        </View>
      );
    },
    [agentLookup, handleContinueSession],
  );

  return (
    <ScreenContainer className="flex-1 bg-background px-5 sm:px-6">
      <PageHeader
        title="Sessions"
        subtitle="Browse sessions across all agents."
        rightElement={
          <View className="flex-row gap-2">
            <AccountEntryButton />
          </View>
        }
      />

      {loading && items.length === 0 ? (
        <View className="mt-8 items-center">
          <Text className="text-sm text-gray-400">Loading sessions...</Text>
        </View>
      ) : (
        <FlatList
          data={sortedItems}
          renderItem={renderSessionItem}
          keyExtractor={(item) => item.conversationId}
          style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
          contentContainerStyle={{ paddingBottom: 18 }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={refresh}
              tintColor="#FFFFFF"
              colors={["#FFFFFF"]}
            />
          }
          ListEmptyComponent={
            <View className="mt-8 rounded-2xl bg-surface p-6">
              <Text className="text-base font-bold text-white">
                No sessions
              </Text>
              <Text className="mt-2 text-sm text-gray-400">
                No sessions found.
              </Text>
            </View>
          }
          onEndReached={() => {
            if (hasMore && !loadingMore) {
              loadMore();
            }
          }}
          onEndReachedThreshold={0.5}
          ListFooterComponent={
            hasMore ? (
              <View className="py-4 items-center">
                <Button
                  label={loadingMore ? "Loading..." : "Load more"}
                  size="sm"
                  variant="secondary"
                  loading={loadingMore}
                  onPress={() => loadMore()}
                />
              </View>
            ) : null
          }
        />
      )}
    </ScreenContainer>
  );
}
