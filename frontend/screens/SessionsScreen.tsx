import { useMemo } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import {
  LIST_CARD_AGENT_TEXT_CLASS,
  LIST_CARD_FOOTER_CLASS,
  LIST_CARD_HEADER_CLASS,
  LIST_CARD_META_TEXT_CLASS,
  LIST_CARD_SURFACE_CLASS,
} from "@/components/layout/listCardStyles";
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

  return (
    <ScreenContainer className="flex-1 bg-background px-5 sm:px-6">
      <PageHeader
        title="Sessions"
        subtitle="Browse sessions across all agents."
      />

      <ScrollView
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
                  className={LIST_CARD_SURFACE_CLASS}
                >
                  <View className={`${LIST_CARD_HEADER_CLASS} pb-3.5`}>
                    <View className="flex-row items-center justify-between mb-1.5">
                      <Text
                        className={LIST_CARD_AGENT_TEXT_CLASS}
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
                      {title}
                    </Text>
                  </View>

                  <View className={LIST_CARD_FOOTER_CLASS}>
                    <View className="flex-1">
                      <Text className={LIST_CARD_META_TEXT_CLASS}>
                        {timeline.timelineRangeText}
                      </Text>
                    </View>
                    <View className="flex-row items-center">
                      {/* Async Continue is intentionally hidden for now. See #381. */}
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
