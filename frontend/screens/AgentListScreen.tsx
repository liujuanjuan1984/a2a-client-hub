import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

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
  checkAgentHealth,
  checkAgentsHealth,
  type A2AAgentResponse,
} from "@/lib/api/a2aAgents";
import { type HubA2AAgentUserResponse } from "@/lib/api/hubA2aAgentsUser";
import { blurActiveElement } from "@/lib/focus";
import { queryKeys } from "@/lib/queryKeys";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useSessionStore } from "@/store/session";

const PERSONAL_PAGE_SIZE = 12;
const SHARED_PAGE_SIZE = 8;

const HEALTH_BADGE_STYLES: Record<
  A2AAgentResponse["health_status"],
  { label: string; className: string }
> = {
  healthy: {
    label: "Healthy",
    className: "bg-emerald-500/20 text-emerald-300",
  },
  degraded: {
    label: "Degraded",
    className: "bg-amber-500/20 text-amber-200",
  },
  unavailable: {
    label: "Unavailable",
    className: "bg-rose-500/20 text-rose-200",
  },
  unknown: {
    label: "Unknown",
    className: "bg-slate-500/20 text-slate-300",
  },
};

export function AgentListScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useSessionStore((state) => state.user);
  const setActiveAgent = useAgentStore((state) => state.setActiveAgent);
  const [personalPage, setPersonalPage] = useState(1);
  const [attentionPage, setAttentionPage] = useState(1);
  const [sharedPage, setSharedPage] = useState(1);
  const [showAttention, setShowAttention] = useState(false);
  const [checkingAgentId, setCheckingAgentId] = useState<string | null>(null);

  const personalQuery = usePersonalAgentsListQuery({
    page: personalPage,
    size: PERSONAL_PAGE_SIZE,
    healthBucket: "healthy",
  });

  const counts = personalQuery.data?.meta.counts;
  const attentionCount = useMemo(() => {
    if (!counts) {
      return 0;
    }
    return counts.degraded + counts.unavailable + counts.unknown;
  }, [counts]);

  const attentionQuery = usePersonalAgentsListQuery({
    page: attentionPage,
    size: PERSONAL_PAGE_SIZE,
    healthBucket: "attention",
    enabled: showAttention && attentionCount > 0,
  });

  const sharedQuery = useSharedAgentsListQuery({
    page: sharedPage,
    size: SHARED_PAGE_SIZE,
  });

  const isFetching =
    personalQuery.isFetching ||
    attentionQuery.isFetching ||
    sharedQuery.isFetching;

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

  const handleCheckAgent = async (agentId: string) => {
    setCheckingAgentId(agentId);
    try {
      await checkAgentHealth(agentId, true);
      await invalidateAgentQueries();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Could not check agent availability.";
      toast.error("Availability check failed", message);
    } finally {
      setCheckingAgentId(null);
    }
  };

  const onRefresh = async () => {
    const results = await Promise.allSettled([
      personalQuery.refetch(),
      sharedQuery.refetch(),
      ...(showAttention ? [attentionQuery.refetch()] : []),
    ]);
    const failed = results.find(
      (result) => result.status === "rejected" || result.value.error,
    );
    if (failed) {
      const message =
        failed.status === "rejected"
          ? failed.reason instanceof Error
            ? failed.reason.message
            : "Could not load agents from server."
          : failed.value.error instanceof Error
            ? failed.value.error.message
            : "Could not load agents from server.";
      toast.error("Refresh failed", message);
    }
  };

  const handleChat = (agentId: string) => {
    setActiveAgent(agentId);
    const chatStore = useChatStore.getState();
    const latestSessionId = chatStore.getLatestConversationIdByAgentId(agentId);

    const conversationId =
      latestSessionId ?? chatStore.generateConversationId();
    blurActiveElement();
    router.push(buildChatRoute(agentId, conversationId));
  };

  const renderPersonalAgentItem = (agent: A2AAgentResponse) => {
    const badge = HEALTH_BADGE_STYLES[agent.health_status];
    const isCheckingThisAgent = checkingAgentId === agent.id;

    return (
      <View
        key={agent.id}
        className="mb-4 overflow-hidden rounded-2xl bg-surface shadow-sm"
      >
        <View className="px-4 py-4">
          <View className="flex-row items-center justify-between">
            <Text
              className="flex-1 pr-4 text-[13px] font-semibold text-white"
              numberOfLines={1}
            >
              {agent.name}
            </Text>
            <View className="items-end gap-2">
              <Text
                className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest ${badge.className}`}
              >
                {badge.label}
              </Text>
              <Text className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
                PERSONAL
              </Text>
            </View>
          </View>
          <View className="mt-3 flex-row items-center justify-between gap-3">
            <Text className="text-xs text-slate-400" numberOfLines={1}>
              {agent.enabled ? "Enabled" : "Disabled"}
            </Text>
            <Text
              className="flex-1 text-right text-xs text-slate-500"
              numberOfLines={1}
            >
              {agent.last_health_check_at
                ? `Checked ${new Date(agent.last_health_check_at).toLocaleString()}`
                : "Not checked yet"}
            </Text>
          </View>
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
            <Button
              label={isCheckingThisAgent ? "Checking..." : "Check"}
              size="sm"
              variant="secondary"
              iconLeft="pulse-outline"
              onPress={() => {
                if (isCheckingThisAgent) {
                  return;
                }
                handleCheckAgent(agent.id).catch(() => undefined);
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
  };

  const renderSharedAgentItem = (agent: HubA2AAgentUserResponse) => (
    <View
      key={agent.id}
      className="mb-4 overflow-hidden rounded-2xl bg-surface shadow-sm"
    >
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
      </View>

      <View className="flex-row items-center justify-between gap-2 bg-black/20 px-4 py-2.5">
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

  const renderPagination = ({
    page,
    pages,
    onPrevious,
    onNext,
  }: {
    page: number;
    pages: number;
    onPrevious: () => void;
    onNext: () => void;
  }) => {
    if (pages <= 1) {
      return null;
    }

    return (
      <View className="mb-6 flex-row items-center justify-between gap-3">
        <Button
          label="Previous"
          size="sm"
          variant="secondary"
          onPress={() => {
            if (page > 1) {
              onPrevious();
            }
          }}
        />
        <Text className="text-xs font-semibold uppercase tracking-widest text-slate-400">
          Page {page} / {pages}
        </Text>
        <Button
          label="Next"
          size="sm"
          variant="secondary"
          onPress={() => {
            if (page < pages) {
              onNext();
            }
          }}
        />
      </View>
    );
  };

  const healthyAgents = personalQuery.data?.items ?? [];
  const attentionAgents = attentionQuery.data?.items ?? [];
  const sharedAgents = sharedQuery.data?.items ?? [];
  const showEmptyState =
    healthyAgents.length === 0 &&
    attentionCount === 0 &&
    sharedAgents.length === 0;

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

      <ScrollView
        style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
        contentContainerStyle={{ paddingBottom: 18 }}
        refreshControl={
          <RefreshControl
            refreshing={isFetching}
            onRefresh={onRefresh}
            tintColor="#FFFFFF"
            colors={["#FFFFFF"]}
          />
        }
      >
        <View className="mb-5 rounded-2xl bg-surface p-4">
          <View className="flex-row items-center justify-between gap-3">
            <View className="flex-1">
              <Text className="text-sm font-semibold text-white">
                My Agents
              </Text>
              <Text className="mt-1 text-xs text-slate-400">
                Healthy agents stay visible. Degraded, unavailable, and unknown
                agents are grouped below.
              </Text>
            </View>
            <Button
              label={
                batchHealthMutation.isPending
                  ? "Checking..."
                  : "Check availability"
              }
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
            <Text className="rounded-full bg-emerald-500/20 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-emerald-300">
              Healthy {counts?.healthy ?? 0}
            </Text>
            <Text className="rounded-full bg-amber-500/20 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-amber-200">
              Degraded {counts?.degraded ?? 0}
            </Text>
            <Text className="rounded-full bg-rose-500/20 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-rose-200">
              Unavailable {counts?.unavailable ?? 0}
            </Text>
            <Text className="rounded-full bg-slate-500/20 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-300">
              Unknown {counts?.unknown ?? 0}
            </Text>
          </View>
        </View>

        {healthyAgents.map(renderPersonalAgentItem)}

        {renderPagination({
          page: personalPage,
          pages: personalQuery.data?.pagination.pages ?? 0,
          onPrevious: () => setPersonalPage((value) => Math.max(1, value - 1)),
          onNext: () => setPersonalPage((value) => value + 1),
        })}

        {attentionCount > 0 ? (
          <View className="mb-6 rounded-2xl bg-surface p-4">
            <View className="flex-row items-center justify-between gap-3">
              <View className="flex-1">
                <Text className="text-sm font-semibold text-white">
                  Need attention ({attentionCount})
                </Text>
                <Text className="mt-1 text-xs text-slate-400">
                  Includes degraded, unavailable, and not-yet-checked personal
                  agents.
                </Text>
              </View>
              <Button
                label={showAttention ? "Collapse" : "Expand"}
                size="sm"
                variant="secondary"
                onPress={() => {
                  setShowAttention((value) => !value);
                }}
              />
            </View>

            {showAttention ? (
              <View className="mt-4">
                {attentionAgents.map(renderPersonalAgentItem)}
                {renderPagination({
                  page: attentionPage,
                  pages: attentionQuery.data?.pagination.pages ?? 0,
                  onPrevious: () =>
                    setAttentionPage((value) => Math.max(1, value - 1)),
                  onNext: () => setAttentionPage((value) => value + 1),
                })}
              </View>
            ) : null}
          </View>
        ) : null}

        <View className="mb-4">
          <Text className="mb-3 text-sm font-semibold text-white">
            Shared Agents
          </Text>
          {sharedAgents.map(renderSharedAgentItem)}
          {renderPagination({
            page: sharedPage,
            pages: sharedQuery.data?.pagination.pages ?? 0,
            onPrevious: () => setSharedPage((value) => Math.max(1, value - 1)),
            onNext: () => setSharedPage((value) => value + 1),
          })}
        </View>

        {showEmptyState ? (
          <View className="items-center rounded-2xl bg-surface p-8">
            <View className="mb-4 h-16 w-16 items-center justify-center rounded-2xl bg-primary">
              <Text className="text-[11px] font-bold text-black">A2A</Text>
            </View>
            <Text className="text-base font-bold text-white">
              No agents yet
            </Text>
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
        ) : null}
      </ScrollView>
    </ScreenContainer>
  );
}
