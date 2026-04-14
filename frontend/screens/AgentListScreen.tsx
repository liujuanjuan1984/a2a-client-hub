import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { FlatList, RefreshControl, Text, View } from "react-native";

import { AccountEntryButton } from "@/components/auth/AccountEntryButton";
import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import {
  checkAgentsCatalogHealth,
  type UnifiedAgentHealthStatus,
} from "@/lib/api/agentsCatalog";
import { formatLocalDateTime } from "@/lib/datetime";
import { blurActiveElement } from "@/lib/focus";
import { queryKeys } from "@/lib/queryKeys";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { type AgentConfig, useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useSessionStore } from "@/store/session";

type AgentHealthFilter = UnifiedAgentHealthStatus | "all";

const HEALTH_BADGE_STYLES: Record<
  NonNullable<AgentConfig["healthStatus"]>,
  { label: string }
> = {
  healthy: { label: "Healthy" },
  degraded: { label: "Degraded" },
  unavailable: { label: "Unavailable" },
  unknown: { label: "Not checked" },
};

const HEALTH_FILTER_ORDER: UnifiedAgentHealthStatus[] = [
  "healthy",
  "degraded",
  "unavailable",
  "unknown",
];

const SOURCE_LABELS: Record<AgentConfig["source"], string> = {
  personal: "PERSONAL",
  shared: "SHARED",
  builtin: "BUILT-IN",
};

const SOURCE_SORT_ORDER: Record<AgentConfig["source"], number> = {
  builtin: 0,
  personal: 1,
  shared: 2,
};

const resolveHealthStatus = (agent: AgentConfig) =>
  agent.healthStatus ?? "unknown";

export function AgentListScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useSessionStore((state) => state.user);
  const setActiveAgent = useAgentStore((state) => state.setActiveAgent);
  const [activeHealthFilter, setActiveHealthFilter] =
    useState<AgentHealthFilter>("healthy");
  const {
    data: agents = [],
    isLoading,
    isRefetching,
    refetch,
    error,
  } = useAgentsCatalogQuery(true);

  const orderedAgents = useMemo(
    () =>
      [...agents].sort((left, right) => {
        const sourceDelta =
          SOURCE_SORT_ORDER[left.source] - SOURCE_SORT_ORDER[right.source];
        if (sourceDelta !== 0) {
          return sourceDelta;
        }
        return left.name.localeCompare(right.name);
      }),
    [agents],
  );

  const healthCounts = useMemo(
    () =>
      orderedAgents.reduce<Record<UnifiedAgentHealthStatus, number>>(
        (result, agent) => {
          const healthStatus = resolveHealthStatus(agent);
          result[healthStatus] += 1;
          return result;
        },
        {
          healthy: 0,
          degraded: 0,
          unavailable: 0,
          unknown: 0,
        },
      ),
    [orderedAgents],
  );

  const filteredAgents = useMemo(() => {
    if (activeHealthFilter === "all") {
      return orderedAgents;
    }

    return orderedAgents.filter(
      (agent) => resolveHealthStatus(agent) === activeHealthFilter,
    );
  }, [activeHealthFilter, orderedAgents]);

  const counts = useMemo(
    () => ({
      builtin: orderedAgents.filter((agent) => agent.source === "builtin")
        .length,
      personal: orderedAgents.filter((agent) => agent.source === "personal")
        .length,
      shared: orderedAgents.filter((agent) => agent.source === "shared").length,
    }),
    [orderedAgents],
  );

  const selectedHealthFilterLabel =
    activeHealthFilter === "all"
      ? "all"
      : HEALTH_BADGE_STYLES[activeHealthFilter].label.toLowerCase();

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

  const batchHealthMutation = useMutation({
    mutationFn: async () => checkAgentsCatalogHealth(false),
    onSuccess: async () => {
      await Promise.all([
        queryClient.refetchQueries({
          queryKey: queryKeys.agents.catalog(),
          exact: true,
          type: "active",
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.agents.listRoot(),
        }),
      ]);
    },
    onError: (mutationError) => {
      const message =
        mutationError instanceof Error
          ? mutationError.message
          : "Could not check agent availability.";
      toast.error("Availability check failed", message);
    },
  });

  const renderAgentMeta = (agent: AgentConfig) => {
    const healthStatus = resolveHealthStatus(agent);
    const checkedAtLabel = agent.lastHealthCheckAt
      ? `Checked ${formatLocalDateTime(agent.lastHealthCheckAt)}`
      : "Not checked yet";
    const sourceLabel = SOURCE_LABELS[agent.source];

    return (
      <>
        <View className="flex-row items-center justify-between gap-3">
          <Text
            className="flex-1 pr-4 text-[13px] font-semibold text-white"
            numberOfLines={1}
          >
            {agent.name}
          </Text>
          <Text className="text-[10px] font-bold uppercase tracking-widest text-neo-green">
            {sourceLabel}
          </Text>
        </View>

        <View className="mt-3 flex-row items-center justify-between gap-3">
          <Text className="text-xs text-slate-400" numberOfLines={1}>
            {HEALTH_BADGE_STYLES[healthStatus].label}
          </Text>
          <Text
            className="flex-1 text-right text-xs text-slate-500"
            numberOfLines={1}
          >
            {checkedAtLabel}
          </Text>
        </View>
      </>
    );
  };

  const renderPersonalAgentItem = (agent: AgentConfig) => (
    <View className="mb-4 overflow-hidden rounded-2xl bg-surface shadow-sm">
      <View className="px-4 py-4">
        {renderAgentMeta(agent)}
        {!agent.enabled ? (
          <Text className="mt-2 text-xs text-slate-400" numberOfLines={1}>
            Disabled
          </Text>
        ) : null}
        {agent.lastHealthCheckError ? (
          <Text className="mt-2 text-xs text-rose-200" numberOfLines={2}>
            {agent.lastHealthCheckError}
          </Text>
        ) : null}
      </View>

      <View className="flex-row items-center justify-between gap-2 bg-black/20 px-4 py-2.5">
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

  const renderSharedAgentItem = (agent: AgentConfig) => (
    <View className="mb-4 overflow-hidden rounded-2xl bg-surface shadow-sm">
      <View className="px-4 py-4">
        {renderAgentMeta(agent)}
        <Text className="mt-3 text-xs text-slate-400">
          {agent.credentialMode === "user"
            ? agent.credentialConfigured
              ? `Uses your saved ${agent.authType} credential${
                  agent.credentialDisplayHint
                    ? ` (${agent.credentialDisplayHint})`
                    : ""
                }.`
              : `Requires your ${agent.authType} credential before chat.`
            : agent.credentialMode === "shared"
              ? "Uses an admin-managed shared credential."
              : "No credential required."}
        </Text>
        {agent.lastHealthCheckError ? (
          <Text className="mt-2 text-xs text-rose-200" numberOfLines={2}>
            {agent.lastHealthCheckError}
          </Text>
        ) : null}
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
          {agent.credentialMode === "user" ? (
            <Button
              label={
                agent.credentialConfigured
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
            agent.credentialMode === "user" && !agent.credentialConfigured
          }
          accessibilityRole="button"
          accessibilityLabel="Open chat"
          accessibilityHint={`Open chat with ${agent.name}`}
        />
      </View>
    </View>
  );

  const renderBuiltInAgentItem = (agent: AgentConfig) => (
    <View className="mb-4 overflow-hidden rounded-2xl bg-surface shadow-sm">
      <View className="px-4 py-4">
        {renderAgentMeta(agent)}
        <Text className="mt-3 text-xs text-slate-400">
          {agent.description ??
            "Manage your agents, sessions, and jobs through constrained built-in tools."}
        </Text>
        {agent.resources?.length ? (
          <Text className="mt-2 text-xs text-slate-500">
            Resources: {agent.resources.join(", ")}
          </Text>
        ) : null}
      </View>

      <View className="flex-row items-center justify-end gap-2 bg-black/20 px-4 py-2.5">
        <Button
          label="Chat"
          size="sm"
          variant="primary"
          iconRight="chevron-forward"
          onPress={() => handleChat(agent.id)}
          accessibilityRole="button"
          accessibilityLabel="Open built-in assistant"
          accessibilityHint={`Open chat with ${agent.name}`}
        />
      </View>
    </View>
  );

  const renderAgentItem = useCallback(
    ({ item }: { item: AgentConfig }) => {
      if (item.source === "builtin") {
        return renderBuiltInAgentItem(item);
      }
      if (item.source === "shared") {
        return renderSharedAgentItem(item);
      }
      return renderPersonalAgentItem(item);
    },
    [handleChat, router],
  );

  const renderHeader = useMemo(
    () => (
      <View className="mb-5 rounded-2xl bg-surface p-4">
        <View className="flex-row items-center justify-between gap-4">
          <View className="flex-1">
            <Text className="text-sm font-semibold text-white">
              {filteredAgents.length} of {orderedAgents.length} agents
            </Text>
            <Text className="mt-1 text-xs text-slate-400">
              Built-in {counts.builtin} / Personal {counts.personal} / Shared{" "}
              {counts.shared}
            </Text>
          </View>
          <Button
            label={batchHealthMutation.isPending ? "Checking..." : "Check all"}
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

        <View className="mt-4 flex-row flex-wrap items-center gap-3">
          <Button
            className="rounded-full"
            label={`All ${orderedAgents.length}`}
            size="xs"
            variant={activeHealthFilter === "all" ? "primary" : "secondary"}
            onPress={() => setActiveHealthFilter("all")}
          />
          {HEALTH_FILTER_ORDER.map((status) => (
            <Button
              key={status}
              className="rounded-full"
              label={`${HEALTH_BADGE_STYLES[status].label} ${healthCounts[status]}`}
              size="xs"
              variant={activeHealthFilter === status ? "primary" : "secondary"}
              onPress={() => setActiveHealthFilter(status)}
            />
          ))}
        </View>
      </View>
    ),
    [
      activeHealthFilter,
      batchHealthMutation,
      counts,
      filteredAgents.length,
      healthCounts,
      orderedAgents.length,
    ],
  );

  return (
    <ScreenContainer className="flex-1 bg-background px-5 sm:px-6">
      <PageHeader
        title="Agents"
        subtitle="Browse agents and check whether each one is available to you."
        rightElement={
          <View className="flex-row gap-2">
            <AccountEntryButton />
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

      {isLoading && orderedAgents.length === 0 ? (
        <View className="mt-8 items-center">
          <Text className="text-sm text-gray-400">Loading agents...</Text>
        </View>
      ) : error ? (
        <View className="mt-8 rounded-2xl bg-surface p-6">
          <Text className="text-base font-bold text-white">Load failed</Text>
          <Text className="mt-2 text-sm text-gray-400">
            {error instanceof Error ? error.message : "Could not load agents."}
          </Text>
        </View>
      ) : (
        <FlatList
          data={filteredAgents}
          renderItem={renderAgentItem}
          keyExtractor={(item) => `${item.source}:${item.id}`}
          style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
          contentContainerStyle={{ paddingBottom: 18 }}
          refreshControl={
            <RefreshControl
              refreshing={isRefetching}
              onRefresh={() => {
                refetch().catch(() => undefined);
              }}
              tintColor="#FFFFFF"
              colors={["#FFFFFF"]}
            />
          }
          ListHeaderComponent={renderHeader}
          ListEmptyComponent={
            orderedAgents.length === 0 ? (
              <View className="items-center rounded-2xl bg-surface p-8">
                <View className="mb-4 h-16 w-16 items-center justify-center rounded-2xl bg-primary">
                  <Text className="text-[11px] font-bold text-black">A2A</Text>
                </View>
                <Text className="text-base font-bold text-white">
                  No agents available
                </Text>
                <Text className="mt-2 text-center text-sm text-slate-400">
                  Add your first personal agent or wait for shared agents to be
                  published.
                </Text>
              </View>
            ) : (
              <View className="items-center rounded-2xl bg-surface p-8">
                <Text className="text-base font-bold text-white">
                  No {selectedHealthFilterLabel} agents right now
                </Text>
                <Text className="mt-2 text-center text-sm text-slate-400">
                  Switch to another health status or run Check all to refresh
                  the latest results.
                </Text>
              </View>
            )
          }
        />
      )}
    </ScreenContainer>
  );
}
