import { useMemo } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
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

  return (
    <ScreenContainer>
      <PageHeader
        title="Sessions"
        subtitle="Browse sessions across all agents."
      />

      <ScrollView
        style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={refresh}
            tintColor="#FFFFFF"
            colors={["#FFFFFF"]}
          />
        }
      >
        {loading ? (
          <View className="mt-8 items-center">
            <Text className="text-sm text-gray-400">Loading sessions...</Text>
          </View>
        ) : sortedItems.length === 0 ? (
          <View className="mt-8 rounded-2xl bg-surface p-6">
            <Text className="text-base font-bold text-white">No sessions</Text>
            <Text className="mt-2 text-sm text-gray-400">
              No sessions found.
            </Text>
          </View>
        ) : (
          <>
            {sortedItems.map((item) => {
              const title = item.title;
              const agent = resolveSessionAgentPresentation(item, agentLookup);
              const timeline = getSessionTimelineText(item);
              return (
                <View
                  key={item.conversationId}
                  className="mb-4 rounded-2xl bg-surface overflow-hidden shadow-sm"
                >
                  <View className="p-5 pb-4">
                    <View className="flex-row items-center justify-between mb-1.5">
                      <Text
                        className="text-[11px] font-semibold uppercase tracking-widest text-neo-green"
                        numberOfLines={1}
                      >
                        {agent.name}
                      </Text>
                      <Text className="text-[9px] font-bold text-slate-700 uppercase">
                        {item.source}
                      </Text>
                    </View>
                    <Text
                      className="text-base font-medium text-white/90"
                      numberOfLines={2}
                    >
                      {title}
                    </Text>
                  </View>

                  <View className="flex-row items-center justify-between gap-3 bg-black/30 px-5 py-2">
                    <View className="flex-1">
                      <Text className="text-[11px] font-medium text-slate-500">
                        {timeline.timelineRangeText}
                      </Text>
                    </View>
                    <View className="flex-row items-center">
                      {/* Async Continue is intentionally hidden for now. See #381. */}
                      <IconButton
                        size="xs"
                        variant="primary"
                        icon="chevron-forward"
                        accessibilityLabel="Continue session"
                        disabled={!item.agent_id}
                        onPress={() => handleContinueSession(item)}
                        className="rounded-full w-7 h-7"
                      />
                    </View>
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
    </ScreenContainer>
  );
}
