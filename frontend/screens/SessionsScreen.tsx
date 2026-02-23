import { useMemo } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

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
          <RefreshControl refreshing={refreshing} onRefresh={refresh} />
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
            <Text className="mt-2 text-sm text-muted">No sessions found.</Text>
          </View>
        ) : (
          <>
            {sortedItems.map((item) => {
              const title = item.title;
              const agent = resolveSessionAgentPresentation(item, agentLookup);
              const timeline = getSessionTimelineText(item);
              const agentBadgeClass =
                agent.tone === "shared"
                  ? "bg-sky-500/20"
                  : agent.tone === "personal"
                    ? "bg-emerald-500/20"
                    : "bg-slate-700";
              const agentTextClass =
                agent.tone === "shared"
                  ? "text-sky-200"
                  : agent.tone === "personal"
                    ? "text-emerald-200"
                    : "text-slate-200";
              return (
                <View
                  key={item.conversationId}
                  className="mb-3 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/30"
                >
                  <View className="p-4">
                    <View className="flex-row items-center justify-between gap-2">
                      <View
                        className={`max-w-[78%] rounded-full px-3 py-1 ${agentBadgeClass}`}
                      >
                        <Text
                          className={`text-[11px] font-semibold ${agentTextClass}`}
                          numberOfLines={1}
                        >
                          {agent.name}
                        </Text>
                      </View>
                      <View className="px-1 py-0.5">
                        <Text className="text-[10px] text-slate-500">
                          {item.source}
                        </Text>
                      </View>
                    </View>
                    <Text
                      className="mt-2 text-sm text-slate-300"
                      numberOfLines={2}
                    >
                      {title}
                    </Text>
                  </View>

                  <View className="flex-row items-start justify-between gap-3 border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
                    <View className="flex-1">
                      <Text className="text-xs text-slate-400">
                        Created: {timeline.createdAtText}
                      </Text>
                      <Text className="text-xs text-slate-300">
                        Last updated: {timeline.lastUpdatedAtText}
                      </Text>
                    </View>
                    <Button
                      size="xs"
                      variant="secondary"
                      label="Continue"
                      iconRight="chevron-forward"
                      disabled={!item.agent_id}
                      onPress={() => handleContinueSession(item)}
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
    </ScreenContainer>
  );
}
