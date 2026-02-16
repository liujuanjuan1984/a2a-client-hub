import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  useAgentsCatalogQuery,
  useValidateAgentMutation,
} from "@/hooks/useAgentsCatalogQuery";
import { AGENT_ERROR_MESSAGES } from "@/lib/agentCatalogCache";
import { blurActiveElement } from "@/lib/focus";
import { queryKeys } from "@/lib/queryKeys";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import {
  type AgentConfig,
  type AgentStatus,
  useAgentStore,
} from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useSessionStore } from "@/store/session";

const statusIndicatorConfig = (status: AgentStatus) => {
  if (status === "success") {
    return { label: "Connected", dotClassName: "bg-emerald-400" };
  }
  if (status === "checking") {
    return { label: "Checking", dotClassName: "bg-amber-400" };
  }
  if (status === "error") {
    return { label: "Failed", dotClassName: "bg-red-400" };
  }
  return { label: "Idle", dotClassName: "bg-slate-400" };
};

export function AgentListScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useSessionStore((state) => state.user);
  const setActiveAgent = useAgentStore((state) => state.setActiveAgent);

  const {
    data: agents = [],
    isFetching,
    refetch,
  } = useAgentsCatalogQuery(true);
  const validateAgentMutation = useValidateAgentMutation();

  const onRefresh = async () => {
    const result = await refetch();
    if (result.error) {
      const message =
        result.error instanceof Error
          ? result.error.message
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

  const handleTest = async (agentId: string) => {
    blurActiveElement();
    try {
      await validateAgentMutation.mutateAsync(agentId);
    } catch (error) {
      if (
        error instanceof Error &&
        error.message === AGENT_ERROR_MESSAGES.notFound
      ) {
        toast.error("Agent unavailable", error.message);
        return;
      }
    }

    const updated = queryClient
      .getQueryData<AgentConfig[]>(queryKeys.agents.catalog())
      ?.find((item) => item.id === agentId);
    if (!updated) return;

    if (updated.status === "success") {
      toast.success("Connection OK", `${updated.name} is online.`);
    } else if (updated.status === "error") {
      toast.error("Connection failed", updated.lastError);
    }
  };

  return (
    <ScreenContainer>
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
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl
            refreshing={isFetching}
            onRefresh={onRefresh}
            tintColor="#5c6afb"
            colors={["#5c6afb"]}
          />
        }
      >
        {agents.length === 0 ? (
          <View className="rounded-3xl border border-slate-800 bg-slate-900/50 p-8 items-center">
            <View className="h-16 w-16 items-center justify-center rounded-full bg-slate-800 mb-4">
              <Text className="text-xs font-bold text-slate-500">A2A</Text>
            </View>
            <Text className="text-lg font-semibold text-white">
              No agents yet
            </Text>
            <Text className="mt-2 text-center text-sm text-muted">
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
        ) : (
          agents.map((agent) => {
            const statusCfg = statusIndicatorConfig(agent.status);

            return (
              <View
                key={agent.id}
                className="mb-4 overflow-hidden rounded-3xl border border-slate-800 bg-slate-900/30"
              >
                <View className="p-5">
                  <View className="flex-row items-start justify-between">
                    <View className="flex-1 pr-4">
                      <Text
                        className="text-xl font-bold text-white"
                        numberOfLines={1}
                      >
                        {agent.name}
                      </Text>
                      <Text
                        className="mt-1 break-all text-xs text-muted"
                        numberOfLines={1}
                      >
                        {agent.cardUrl}
                      </Text>
                      {agent.source === "shared" ? (
                        <View className="mt-2 self-start rounded-full bg-slate-800/60 px-2.5 py-1">
                          <Text className="text-[11px] font-semibold text-slate-200">
                            Shared
                          </Text>
                        </View>
                      ) : null}

                      {agent.lastError ? (
                        <View className="mt-3 rounded-xl border border-red-500/20 bg-red-500/10 p-3">
                          <Text
                            className="text-xs text-red-400"
                            numberOfLines={2}
                          >
                            {agent.lastError}
                          </Text>
                        </View>
                      ) : null}
                    </View>

                    <View className="flex-row items-center gap-2">
                      {agent.status === "checking" ? (
                        <ActivityIndicator size="small" color="#ffffff" />
                      ) : (
                        <View
                          className={`h-2.5 w-2.5 rounded-full ${statusCfg.dotClassName}`}
                        />
                      )}
                      <Text className="text-xs font-semibold text-slate-200">
                        {statusCfg.label}
                      </Text>
                    </View>
                  </View>
                </View>

                <View className="flex-row items-center justify-between gap-3 border-t border-slate-800/50 bg-slate-900/50 px-5 py-3">
                  <View className="flex-row items-center gap-2">
                    <Pressable
                      className={`flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40 ${
                        agent.status === "checking" ? "opacity-50" : ""
                      }`}
                      onPress={
                        agent.status === "checking"
                          ? undefined
                          : () => handleTest(agent.id)
                      }
                      disabled={agent.status === "checking"}
                      accessibilityRole="button"
                      accessibilityLabel="Test agent connection"
                      accessibilityHint={`Test connection to ${agent.name}`}
                    >
                      <Ionicons
                        name="pulse-outline"
                        size={14}
                        color="#94a3b8"
                      />
                      <Text className="text-xs font-medium text-slate-400">
                        Test
                      </Text>
                    </Pressable>

                    {agent.source === "personal" ? (
                      <Pressable
                        className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
                        onPress={() => {
                          blurActiveElement();
                          router.push(`/agents/${agent.id}`);
                        }}
                        accessibilityRole="button"
                        accessibilityLabel="Edit agent"
                        accessibilityHint={`Edit ${agent.name}`}
                      >
                        <Ionicons
                          name="create-outline"
                          size={14}
                          color="#94a3b8"
                        />
                        <Text className="text-xs font-medium text-slate-400">
                          Edit
                        </Text>
                      </Pressable>
                    ) : null}
                  </View>

                  <Button
                    label="Open Chat"
                    size="sm"
                    iconRight="chevron-forward"
                    onPress={() => handleChat(agent.id)}
                    accessibilityRole="button"
                    accessibilityLabel="Open chat"
                    accessibilityHint={`Open chat with ${agent.name}`}
                  />
                </View>
              </View>
            );
          })
        )}
      </ScrollView>
    </ScreenContainer>
  );
}
