import { useMemo } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { useContinueSession } from "@/hooks/useContinueSession";
import { useSessionsDirectoryQuery } from "@/hooks/useSessionsDirectoryQuery";
import { type SessionListItem } from "@/lib/api/sessions";
import { formatLocalDateTimeYmdHm } from "@/lib/datetime";

export function SessionsScreen() {
  const { continueSession } = useContinueSession();

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

  const handleContinueSession = async (item: SessionListItem) => {
    if (!item.agent_id) return;
    await continueSession({
      agentId: item.agent_id,
      sessionId: item.id,
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
              const ts = item.last_active_at ?? null;
              return (
                <View
                  key={item.id}
                  className="mb-3 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/30"
                >
                  <View className="p-4">
                    <Text
                      className="text-base font-semibold text-white"
                      numberOfLines={1}
                    >
                      {item.source}
                    </Text>
                    <Text
                      className="mt-1 text-sm text-slate-100"
                      numberOfLines={1}
                    >
                      {title}
                    </Text>
                  </View>

                  <View className="flex-row items-center justify-between gap-3 border-t border-slate-800/50 bg-slate-900/50 px-4 py-3">
                    <View className="flex-1">
                      <Text className="text-xs text-slate-200">
                        {formatLocalDateTimeYmdHm(ts)}
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
