import { useMemo, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { useContinueSession } from "@/hooks/useContinueSession";
import { useSessionsDirectoryQuery } from "@/hooks/useSessionsDirectoryQuery";
import {
  A2AExtensionCallError,
  promptOpencodeSessionAsync,
} from "@/lib/api/a2aExtensions";
import { type SessionListItem } from "@/lib/api/sessions";
import {
  getSessionTimelineText,
  resolveSessionAgentPresentation,
} from "@/lib/sessionDirectoryPresentation";
import { toast } from "@/lib/toast";

export function SessionsScreen() {
  const { continueSession } = useContinueSession();
  const { data: agents = [] } = useAgentsCatalogQuery(true);
  const [promptingConversationId, setPromptingConversationId] = useState<
    string | null
  >(null);

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

  const resolvePromptSource = (
    item: SessionListItem,
  ): "personal" | "shared" | null => {
    if (item.agent_source === "personal" || item.agent_source === "shared") {
      return item.agent_source;
    }
    if (!item.agent_id) {
      return null;
    }
    const fallbackSource = agentLookup.get(item.agent_id)?.source;
    if (fallbackSource === "personal" || fallbackSource === "shared") {
      return fallbackSource;
    }
    return null;
  };

  const canPromptAsync = (item: SessionListItem) =>
    item.external_provider === "opencode" &&
    typeof item.external_session_id === "string" &&
    item.external_session_id.trim().length > 0 &&
    typeof item.agent_id === "string" &&
    item.agent_id.trim().length > 0 &&
    resolvePromptSource(item) !== null;

  const handlePromptAsync = async (item: SessionListItem) => {
    if (!canPromptAsync(item)) {
      return;
    }
    const sessionId = item.external_session_id!.trim();
    const agentId = item.agent_id!.trim();
    const source = resolvePromptSource(item);
    if (!source) {
      return;
    }
    setPromptingConversationId(item.conversationId);
    try {
      await promptOpencodeSessionAsync({
        source,
        agentId,
        sessionId,
        request: {
          parts: [
            {
              type: "text",
              text: "Continue from the latest context and summarize next steps.",
            },
          ],
          noReply: true,
        },
      });
      toast.success(
        "Async continue started",
        "The upstream session accepted prompt_async.",
      );
      await refresh();
    } catch (error) {
      const message =
        error instanceof A2AExtensionCallError
          ? error.errorCode === "session_forbidden"
            ? "You do not have permission to continue this external session."
            : error.message
          : error instanceof Error
            ? error.message
            : "Failed to trigger async continue.";
      toast.error("Async continue failed", message);
    } finally {
      setPromptingConversationId(null);
    }
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
              const agentBadgeClass =
                agent.tone === "shared"
                  ? "bg-primary/10 border border-primary/20"
                  : "bg-slate-800 border border-slate-700";
              const agentTextClass =
                agent.tone === "shared" ? "text-primary" : "text-slate-400";
              return (
                <View
                  key={item.conversationId}
                  className="mb-4 rounded-2xl bg-surface overflow-hidden"
                >
                  <View className="p-5">
                    <View className="flex-row items-center justify-between gap-2">
                      <View
                        className={`rounded-lg px-2.5 py-0.5 ${agentBadgeClass}`}
                      >
                        <Text
                          className={`text-[10px] font-bold uppercase tracking-wider ${agentTextClass}`}
                          numberOfLines={1}
                        >
                          {agent.name}
                        </Text>
                      </View>
                      <Text className="text-[10px] font-bold text-slate-600 uppercase">
                        {item.source}
                      </Text>
                    </View>
                    <Text
                      className="mt-3 text-lg font-bold text-white"
                      numberOfLines={2}
                    >
                      {title}
                    </Text>
                  </View>

                  <View className="flex-row items-start justify-between gap-3 bg-black/30 px-5 py-3">
                    <View className="flex-1 justify-center h-9">
                      <Text className="text-[11px] font-medium text-slate-500">
                        {timeline.timelineRangeText}
                      </Text>
                    </View>
                    <View className="flex-row items-center gap-2">
                      {canPromptAsync(item) ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          label="Async"
                          loading={
                            promptingConversationId === item.conversationId
                          }
                          disabled={promptingConversationId !== null}
                          onPress={() => handlePromptAsync(item)}
                        />
                      ) : null}
                      <Button
                        size="sm"
                        variant="primary"
                        label="Continue"
                        iconRight="chevron-forward"
                        disabled={!item.agent_id}
                        onPress={() => handleContinueSession(item)}
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
