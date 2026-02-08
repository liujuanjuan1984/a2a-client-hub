import { Redirect, Stack } from "expo-router";
import { useEffect } from "react";
import { Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { useMe } from "@/hooks/useAuth";
import { ApiRequestError } from "@/lib/api/client";
import { useAgentStore } from "@/store/agents";
import { useChatStore } from "@/store/chat";
import { useSessionStore } from "@/store/session";

export default function AppLayout() {
  const token = useSessionStore((state) => state.token);
  const hydrated = useSessionStore((state) => state.hydrated);
  const { isLoading, isError, refetch, error, isFetching } = useMe();
  const loadAgents = useAgentStore((state) => state.loadAgents);
  const cleanupSessions = useChatStore((state) => state.cleanupSessions);

  useEffect(() => {
    cleanupSessions();
  }, [cleanupSessions]);

  const isUnauthorizedError =
    error instanceof ApiRequestError && error.status === 401;
  const shouldShowErrorScreen = isError && !isUnauthorizedError;

  useEffect(() => {
    if (!token) {
      return;
    }
    loadAgents().catch(() => {
      // Agent list failures are handled per screen; keep app shell usable.
    });
  }, [token, loadAgents]);

  if (!hydrated) {
    return <FullscreenLoader message="Loading session..." />;
  }

  if (!token) {
    return <Redirect href="/login" />;
  }

  if (shouldShowErrorScreen) {
    const friendlyMessage =
      error instanceof Error ? error.message : "Unable to sync account.";
    return (
      <View className="flex-1 items-center justify-center bg-background px-6">
        <Text className="text-lg font-semibold text-white">Sync failed</Text>
        <Text className="mt-3 text-center text-base text-muted">
          {friendlyMessage}
        </Text>
        <Button
          className="mt-6"
          label={isFetching ? "Retrying..." : "Retry"}
          onPress={() => refetch()}
          loading={isFetching}
        />
      </View>
    );
  }

  if (isLoading) {
    return <FullscreenLoader message="Syncing account..." />;
  }

  return (
    <Stack
      screenOptions={{
        headerShown: false,
      }}
    >
      <Stack.Screen name="(tabs)" options={{ title: "Home" }} />
      <Stack.Screen
        name="agents/new"
        options={{ title: "Add Agent", presentation: "modal" }}
      />
      <Stack.Screen
        name="agents/[id]"
        options={{ title: "Edit Agent", presentation: "modal" }}
      />
      <Stack.Screen
        name="scheduled-jobs/new"
        options={{ title: "New Job", presentation: "modal" }}
      />
      <Stack.Screen
        name="scheduled-jobs/[id]"
        options={{ title: "Edit Job", presentation: "modal" }}
      />
      <Stack.Screen
        name="chat/[agentId]/[sessionId]"
        options={{ title: "Chat" }}
      />
    </Stack>
  );
}
