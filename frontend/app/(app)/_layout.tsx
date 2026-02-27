import { Redirect, Stack } from "expo-router";
import { useEffect } from "react";
import { AppState, type AppStateStatus, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { useMe } from "@/hooks/useAuth";
import { ApiRequestError } from "@/lib/api/client";
import { useChatStore } from "@/store/chat";
import { useSessionStore } from "@/store/session";

export default function AppLayout() {
  const token = useSessionStore((state) => state.token);
  const hydrated = useSessionStore((state) => state.hydrated);
  const { data, isLoading, isError, refetch, error, isFetching } = useMe();
  const cleanupSessions = useChatStore((state) => state.cleanupSessions);

  useAgentsCatalogQuery(Boolean(token));

  useEffect(() => {
    cleanupSessions();

    const handleLifecycleGc = (nextState: AppStateStatus) => {
      if (nextState !== "active") {
        cleanupSessions();
      } else {
        // Automatically try to resume recoverable sessions
        const chatStore = useChatStore.getState();
        const activeSessions = Object.entries(chatStore.sessions);
        activeSessions.forEach(([conversationId, session]) => {
          if (session.streamState === "recoverable") {
            chatStore.resumeMessage(conversationId).catch(() => {});
          }
        });
      }
    };
    const appStateSub = AppState.addEventListener("change", handleLifecycleGc);
    let lowMemorySub: { remove: () => void } | null = null;
    try {
      lowMemorySub = AppState.addEventListener("memoryWarning", () => {
        cleanupSessions();
      });
    } catch {
      lowMemorySub = null;
    }
    const periodicGcTimer = setInterval(
      () => {
        cleanupSessions();
      },
      5 * 60 * 1000,
    );

    return () => {
      appStateSub.remove();
      lowMemorySub?.remove();
      clearInterval(periodicGcTimer);
    };
  }, [cleanupSessions]);

  const isUnauthorizedError =
    error instanceof ApiRequestError && error.status === 401;
  const shouldShowErrorScreen = isError && !isUnauthorizedError && !data;

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
      <View className="flex-1 items-center justify-center bg-background px-4">
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

  return (
    <View className="flex-1">
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
          name="chat/[agentId]/[conversationId]"
          options={{ title: "Chat" }}
        />
      </Stack>
      {isLoading ? (
        <View pointerEvents="none" className="absolute inset-0">
          <FullscreenLoader message="Syncing account..." />
        </View>
      ) : null}
    </View>
  );
}
