import { useRouter } from "expo-router";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import {
  LIST_CARD_FOOTER_CLASS,
  LIST_CARD_HEADER_CLASS,
  LIST_CARD_SURFACE_CLASS,
} from "@/components/layout/listCardStyles";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useSessionStore } from "@/store/session";

export function AgentListScreen() {
  const router = useRouter();
  const user = useSessionStore((state) => state.user);
  const setActiveAgent = useAgentStore((state) => state.setActiveAgent);

  const {
    data: agents = [],
    isFetching,
    refetch,
  } = useAgentsCatalogQuery(true);

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
        {agents.length === 0 ? (
          <View className="rounded-2xl bg-surface p-8 items-center">
            <View className="h-16 w-16 items-center justify-center rounded-2xl bg-primary mb-4">
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
        ) : (
          agents.map((agent) => (
            <View key={agent.id} className={LIST_CARD_SURFACE_CLASS}>
              <View className={LIST_CARD_HEADER_CLASS}>
                <View className="flex-row items-center justify-between">
                  <Text
                    className="text-[13px] font-semibold text-white flex-1 pr-4"
                    numberOfLines={1}
                  >
                    {agent.name}
                  </Text>
                  <Text
                    className={`text-[10px] font-bold uppercase tracking-widest ${
                      agent.source === "shared"
                        ? "text-neo-green"
                        : "text-slate-500"
                    }`}
                  >
                    {agent.source === "shared" ? "SHARED" : "PERSONAL"}
                  </Text>
                </View>
              </View>

              <View className={LIST_CARD_FOOTER_CLASS}>
                <View className="flex-row items-center gap-2">
                  <Button
                    label={agent.source === "personal" ? "Edit" : "Details"}
                    size="sm"
                    variant="secondary"
                    iconLeft={
                      agent.source === "personal"
                        ? "create-outline"
                        : "information-outline"
                    }
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
          ))
        )}
      </ScrollView>
    </ScreenContainer>
  );
}
