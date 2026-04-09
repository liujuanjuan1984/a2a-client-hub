import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { FlatList, RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  usePersonalAgentsListQuery,
  useSharedAgentsListQuery,
} from "@/hooks/useAgentListQueries";
import {
  checkAgentsHealth,
  type A2AAgentHealthStatus,
  type A2AAgentResponse,
} from "@/lib/api/a2aAgents";
import { type HubA2AAgentUserResponse } from "@/lib/api/hubA2aAgentsUser";
import {
  getSelfManagementBuiltInAgentProfile,
  type SelfManagementBuiltInAgentProfileResponse,
} from "@/lib/api/selfManagementAgent";
import { formatLocalDateTime } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import { queryKeys } from "@/lib/queryKeys";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useSessionStore } from "@/store/session";

const PERSONAL_PAGE_SIZE = 12;
const SHARED_PAGE_SIZE = 8;
const SELF_MANAGEMENT_BUILT_IN_PROFILE_QUERY_KEY = [
  "self-management-built-in-agent",
  "profile",
] as const;

const HEALTH_BADGE_STYLES: Record<
  A2AAgentResponse["health_status"],
  { label: string }
> = {
  healthy: {
    label: "Healthy",
  },
  degraded: {
    label: "Degraded",
  },
  unavailable: {
    label: "Unavailable",
  },
  unknown: {
    label: "Unknown",
  },
};

const PERSONAL_HEALTH_FILTERS: A2AAgentHealthStatus[] = [
  "healthy",
  "degraded",
  "unavailable",
  "unknown",
];

export function AgentListScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useSessionStore((state) => state.user);
  const setActiveAgent = useAgentStore((state) => state.setActiveAgent);
  const [activeView, setActiveView] = useState<"personal" | "shared">(
    "personal",
  );
  const [activePersonalHealthFilter, setActivePersonalHealthFilter] =
    useState<A2AAgentHealthStatus>("healthy");
  const isPersonalView = activeView === "personal";

  const personalQuery = usePersonalAgentsListQuery({
    size: PERSONAL_PAGE_SIZE,
    healthBucket: activePersonalHealthFilter,
    enabled: isPersonalView,
  });

  const sharedQuery = useSharedAgentsListQuery({
    size: SHARED_PAGE_SIZE,
    enabled: !isPersonalView,
  });
  const builtInAgentProfileQuery = useQuery({
    queryKey: SELF_MANAGEMENT_BUILT_IN_PROFILE_QUERY_KEY,
    enabled: !isPersonalView,
    queryFn: getSelfManagementBuiltInAgentProfile,
  });
  const builtInAgentProfile =
    builtInAgentProfileQuery.data?.configured === true
      ? builtInAgentProfileQuery.data
      : null;

  const invalidateAgentQueries = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.agents.listRoot() }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.agents.sharedListRoot(),
      }),
      queryClient.invalidateQueries({ queryKey: queryKeys.agents.catalog() }),
    ]);
  };

  const batchHealthMutation = useMutation({
    mutationFn: async () => checkAgentsHealth(false),
    onSuccess: async () => {
      await invalidateAgentQueries();
    },
    onError: (error) => {
      const message =
        error instanceof Error
          ? error.message
          : "Could not check agent availability.";
      toast.error("Availability check failed", message);
    },
  });

  const counts = personalQuery.counts;
  const visiblePersonalHealthFilters = useMemo(
    () =>
      PERSONAL_HEALTH_FILTERS.filter((status) => (counts?.[status] ?? 0) > 0),
    [counts],
  );
  const totalPersonalAgents = useMemo(() => {
    if (!counts) {
      return 0;
    }
    return (
      counts.healthy + counts.degraded + counts.unavailable + counts.unknown
    );
  }, [counts]);
  const selectedFilterLabel =
    HEALTH_BADGE_STYLES[activePersonalHealthFilter].label.toLowerCase();

  useEffect(() => {
    if (!isPersonalView) {
      return;
    }
    if ((counts?.[activePersonalHealthFilter] ?? 0) > 0) {
      return;
    }
    const fallbackFilter = visiblePersonalHealthFilters[0];
    if (fallbackFilter && fallbackFilter !== activePersonalHealthFilter) {
      setActivePersonalHealthFilter(fallbackFilter);
    }
  }, [
    activePersonalHealthFilter,
    counts,
    isPersonalView,
    visiblePersonalHealthFilters,
  ]);

  const handleChat = useCallback(
    (agentId: string) => {
      setActiveAgent(agentId);
      const chatStore = useChatStore.getState();
      const latestSessionId =
        chatStore.getLatestConversationIdByAgentId(agentId);

      const conversationId =
        latestSessionId ?? chatStore.generateConversationId();
      blurActiveElement();
      router.push(buildChatRoute(agentId, conversationId));
    },
    [router, setActiveAgent],
  );

  const handleRefresh = useCallback(async () => {
    if (activeView === "personal") {
      await personalQuery.refresh();
      return;
    }
    await sharedQuery.refresh();
  }, [activeView, personalQuery, sharedQuery]);

  const handleLoadMore = useCallback(async () => {
    if (activeView === "personal") {
      if (!personalQuery.hasMore || personalQuery.loadingMore) {
        return;
      }
      await personalQuery.loadMore();
      return;
    }

    if (!sharedQuery.hasMore || sharedQuery.loadingMore) {
      return;
    }
    await sharedQuery.loadMore();
  }, [activeView, personalQuery, sharedQuery]);

  const onRefresh = useCallback(() => handleRefresh(), [handleRefresh]);
  const onEndReached = useCallback(() => handleLoadMore(), [handleLoadMore]);
  const toggleActiveView = useCallback(() => {
    setActiveView((currentView) =>
      currentView === "personal" ? "shared" : "personal",
    );
  }, []);

  const activeViewButtonLabel = isPersonalView ? "My" : "Shared";
  const activeViewButtonIcon = isPersonalView ? "person-outline" : "people";

  const renderPersonalAgentItem = useCallback(
    ({ item: agent }: { item: A2AAgentResponse }) => {
      const showCheckedAt = agent.health_status !== "healthy";
      const checkedAtLabel = agent.last_health_check_at
        ? `Checked ${formatLocalDateTime(agent.last_health_check_at)}`
        : "Not checked yet";

      return (
        <View className="mb-4 overflow-hidden rounded-2xl bg-surface shadow-sm">
          <View className="px-4 py-4">
            <Text
              className="text-[13px] font-semibold text-white"
              numberOfLines={1}
            >
              {agent.name}
            </Text>
            {!agent.enabled || showCheckedAt ? (
              <View className="mt-3 flex-row items-center justify-between gap-3">
                {agent.enabled ? (
                  <View className="flex-1" />
                ) : (
                  <Text className="text-xs text-slate-400" numberOfLines={1}>
                    Disabled
                  </Text>
                )}
                {showCheckedAt ? (
                  <Text
                    className="flex-1 text-right text-xs text-slate-500"
                    numberOfLines={1}
                  >
                    {checkedAtLabel}
                  </Text>
                ) : null}
              </View>
            ) : null}
            {agent.last_health_check_error ? (
              <Text className="mt-2 text-xs text-rose-200" numberOfLines={2}>
                {agent.last_health_check_error}
              </Text>
            ) : null}
          </View>

          <View className="flex-row items-center justify-between gap-2 bg-black/20 px-4 py-2.5">
            <View className="flex-row flex-wrap items-center gap-2">
              <Button
                label="Edit"
                size="sm"
                variant="secondary"
                iconLeft="create-outline"
                onPress={() => {
                  blurActiveElement();
                  router.push(`/agents/${agent.id}`);
                }}
              />
            </View>

            <Button
              label="Chat"
              size="sm"
              variant="primary"
              iconRight="chevron-forward"
              onPress={() => handleChat(agent.id)}
              accessibilityRole="button"
              accessibilityLabel="Open chat"
              accessibilityHint={`Open chat with ${agent.name}`}
            />
          </View>
        </View>
      );
    },
    [handleChat, router],
  );

  const renderSharedAgentItem = useCallback(
    ({ item: agent }: { item: HubA2AAgentUserResponse }) => (
      <View className="mb-4 overflow-hidden rounded-2xl bg-surface shadow-sm">
        <View className="px-4 py-4">
          <View className="flex-row items-center justify-between">
            <Text
              className="flex-1 pr-4 text-[13px] font-semibold text-white"
              numberOfLines={1}
            >
              {agent.name}
            </Text>
            <Text className="text-[10px] font-bold uppercase tracking-widest text-neo-green">
              SHARED
            </Text>
          </View>
          <Text className="mt-3 text-xs text-slate-400">
            {agent.credential_mode === "user"
              ? agent.credential_configured
                ? `Uses your saved ${agent.auth_type} credential${
                    agent.credential_display_hint
                      ? ` (${agent.credential_display_hint})`
                      : ""
                  }.`
                : `Requires your ${agent.auth_type} credential before chat.`
              : agent.credential_mode === "shared"
                ? "Uses an admin-managed shared credential."
                : "No credential required."}
          </Text>
        </View>

        <View className="flex-row items-center justify-between gap-2 bg-black/20 px-4 py-2.5">
          <View className="flex-row gap-2">
            <Button
              label="Details"
              size="sm"
              variant="secondary"
              iconLeft="information-outline"
              onPress={() => {
                blurActiveElement();
                router.push(`/agents/${agent.id}`);
              }}
            />
            {agent.credential_mode === "user" ? (
              <Button
                label={
                  agent.credential_configured
                    ? "Edit credential"
                    : "Set credential"
                }
                size="sm"
                variant="secondary"
                iconLeft="key-outline"
                onPress={() => {
                  blurActiveElement();
                  router.push(`/agents/${agent.id}`);
                }}
              />
            ) : null}
          </View>

          <Button
            label="Chat"
            size="sm"
            variant="primary"
            iconRight="chevron-forward"
            onPress={() => handleChat(agent.id)}
            disabled={
              agent.credential_mode === "user" && !agent.credential_configured
            }
            accessibilityRole="button"
            accessibilityLabel="Open chat"
            accessibilityHint={`Open chat with ${agent.name}`}
          />
        </View>
      </View>
    ),
    [handleChat, router],
  );

  const renderBuiltInAgentCard = useCallback(
    (profile: SelfManagementBuiltInAgentProfileResponse) => (
      <View className="mb-4 overflow-hidden rounded-2xl bg-surface shadow-sm">
        <View className="px-4 py-4">
          <View className="flex-row items-center justify-between">
            <Text
              className="flex-1 pr-4 text-[13px] font-semibold text-white"
              numberOfLines={1}
            >
              {profile.name}
            </Text>
            <Text className="text-[10px] font-bold uppercase tracking-widest text-neo-green">
              BUILT-IN
            </Text>
          </View>
          <Text className="mt-3 text-xs text-slate-400">
            Manage your own {profile.resources.join(", ")} inside a2a-client-hub
            through constrained built-in tools.
          </Text>
        </View>

        <View className="flex-row items-center justify-end gap-2 bg-black/20 px-4 py-2.5">
          <Button
            label="Chat"
            size="sm"
            variant="primary"
            iconRight="chevron-forward"
            onPress={() => handleChat(profile.id)}
            accessibilityRole="button"
            accessibilityLabel="Open built-in assistant"
            accessibilityHint={`Open chat with ${profile.name}`}
          />
        </View>
      </View>
    ),
    [handleChat],
  );

  const sharedListData = useMemo(() => sharedQuery.items, [sharedQuery.items]);

  const renderHeader = useMemo(
    () => (
      <View className="mb-5">
        {isPersonalView ? (
          <View className="rounded-2xl bg-surface p-4">
            <View className="flex-row items-center gap-3">
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                className="min-w-0 flex-1"
                contentContainerStyle={{ gap: 12, paddingRight: 4 }}
              >
                {visiblePersonalHealthFilters.map((status) => (
                  <Button
                    key={status}
                    className="rounded-full"
                    label={`${counts?.[status] ?? 0} ${HEALTH_BADGE_STYLES[status].label}`}
                    size="xs"
                    variant={
                      activePersonalHealthFilter === status
                        ? "primary"
                        : "secondary"
                    }
                    onPress={() => setActivePersonalHealthFilter(status)}
                  />
                ))}
              </ScrollView>
              <Button
                label={batchHealthMutation.isPending ? "Checking..." : "Check"}
                size="sm"
                variant="secondary"
                iconLeft="pulse-outline"
                onPress={() => {
                  if (batchHealthMutation.isPending) {
                    return;
                  }
                  batchHealthMutation.mutate();
                }}
              />
            </View>
          </View>
        ) : builtInAgentProfile ? (
          renderBuiltInAgentCard(builtInAgentProfile)
        ) : null}
      </View>
    ),
    [
      activePersonalHealthFilter,
      batchHealthMutation,
      builtInAgentProfile,
      counts,
      isPersonalView,
      renderBuiltInAgentCard,
      setActivePersonalHealthFilter,
      visiblePersonalHealthFilters,
    ],
  );

  const renderFooter = useMemo(() => {
    const hasMore =
      activeView === "personal" ? personalQuery.hasMore : sharedQuery.hasMore;
    const loadingMore =
      activeView === "personal"
        ? personalQuery.loadingMore
        : sharedQuery.loadingMore;

    if (!hasMore) {
      return null;
    }

    return (
      <View className="py-4 items-center">
        <Button
          label={loadingMore ? "Loading..." : "Load more"}
          size="sm"
          variant="secondary"
          loading={loadingMore}
          onPress={handleLoadMore}
        />
      </View>
    );
  }, [
    activeView,
    handleLoadMore,
    personalQuery.hasMore,
    personalQuery.loadingMore,
    sharedQuery.hasMore,
    sharedQuery.loadingMore,
  ]);

  const renderPersonalEmptyState = useMemo(() => {
    if (personalQuery.loading && personalQuery.items.length === 0) {
      return (
        <View className="mt-8 items-center">
          <Text className="text-sm text-gray-400">Loading agents...</Text>
        </View>
      );
    }

    if (totalPersonalAgents === 0) {
      return (
        <View className="items-center rounded-2xl bg-surface p-8">
          <View className="mb-4 h-16 w-16 items-center justify-center rounded-2xl bg-primary">
            <Text className="text-[11px] font-bold text-black">A2A</Text>
          </View>
          <Text className="text-base font-bold text-white">No agents yet</Text>
          <Text className="mt-2 text-center text-sm text-slate-400">
            Add your first agent to start chatting with A2A services.
          </Text>
          <Button
            className="mt-6"
            label="Add an agent"
            onPress={() => {
              blurActiveElement();
              router.push("/agents/new");
            }}
          />
        </View>
      );
    }

    return (
      <View className="items-center rounded-2xl bg-surface p-8">
        <Text className="text-base font-bold text-white">
          No {selectedFilterLabel} agents right now
        </Text>
        <Text className="mt-2 text-center text-sm text-slate-400">
          Try another health status or run an availability check to refresh the
          latest results.
        </Text>
      </View>
    );
  }, [
    personalQuery.items.length,
    personalQuery.loading,
    router,
    selectedFilterLabel,
    totalPersonalAgents,
  ]);

  const renderSharedEmptyState = useMemo(() => {
    if (sharedQuery.loading && sharedQuery.items.length === 0) {
      return (
        <View className="mt-8 items-center">
          <Text className="text-sm text-gray-400">Loading agents...</Text>
        </View>
      );
    }

    return (
      <View className="items-center rounded-2xl bg-surface p-8">
        <View className="mb-4 h-16 w-16 items-center justify-center rounded-2xl bg-primary">
          <Text className="text-[11px] font-bold text-black">A2A</Text>
        </View>
        <Text className="text-base font-bold text-white">
          No more shared agents available
        </Text>
        <Text className="mt-2 text-center text-sm text-slate-400">
          Shared agents published by admins will appear here alongside the
          built-in assistant.
        </Text>
      </View>
    );
  }, [sharedQuery.items.length, sharedQuery.loading]);

  return (
    <ScreenContainer className="flex-1 bg-background px-5 sm:px-6">
      <PageHeader
        title="Agents"
        subtitle="Manage your connected A2A services."
        rightElement={
          <View className="flex-row gap-2">
            {user?.is_superuser ? (
              <IconButton
                accessibilityLabel="Open admin"
                icon="shield-checkmark-outline"
                size="sm"
                variant="secondary"
                onPress={() => {
                  blurActiveElement();
                  router.push("/admin");
                }}
              />
            ) : null}
            <Button
              label={activeViewButtonLabel}
              size="sm"
              variant="secondary"
              iconLeft={activeViewButtonIcon}
              accessibilityLabel={`Switch to ${
                isPersonalView ? "shared" : "my"
              } agents`}
              accessibilityHint={`Currently showing ${activeViewButtonLabel.toLowerCase()} agents`}
              onPress={toggleActiveView}
            />
            <IconButton
              accessibilityLabel="Add agent"
              icon="add"
              size="sm"
              onPress={() => {
                blurActiveElement();
                router.push("/agents/new");
              }}
            />
          </View>
        }
      />

      {isPersonalView ? (
        <FlatList
          data={personalQuery.items}
          renderItem={renderPersonalAgentItem}
          keyExtractor={(item) => item.id}
          style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
          contentContainerStyle={{ paddingBottom: 18 }}
          refreshControl={
            <RefreshControl
              refreshing={personalQuery.refreshing}
              onRefresh={onRefresh}
              tintColor="#FFFFFF"
              colors={["#FFFFFF"]}
            />
          }
          ListHeaderComponent={renderHeader}
          ListEmptyComponent={renderPersonalEmptyState}
          ListFooterComponent={renderFooter}
          onEndReached={onEndReached}
          onEndReachedThreshold={0.5}
        />
      ) : (
        <FlatList
          data={sharedListData}
          renderItem={renderSharedAgentItem}
          keyExtractor={(item) => item.id}
          style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
          contentContainerStyle={{ paddingBottom: 18 }}
          refreshControl={
            <RefreshControl
              refreshing={sharedQuery.refreshing}
              onRefresh={onRefresh}
              tintColor="#FFFFFF"
              colors={["#FFFFFF"]}
            />
          }
          ListHeaderComponent={renderHeader}
          ListEmptyComponent={renderSharedEmptyState}
          ListFooterComponent={renderFooter}
          onEndReached={onEndReached}
          onEndReachedThreshold={0.5}
        />
      )}
    </ScreenContainer>
  );
}
