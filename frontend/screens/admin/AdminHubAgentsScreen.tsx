import Ionicons from "@expo/vector-icons/Ionicons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import { listHubAgentsAdmin } from "@/lib/api/hubA2aAgentsAdmin";
import { blurActiveElement } from "@/lib/focus";
import { queryKeys } from "@/lib/queryKeys";

const pill = (label: string, variant: "primary" | "muted") => (
  <View
    className={`self-start rounded-lg px-2.5 py-0.5 ${
      variant === "primary"
        ? "bg-primary/10 border border-primary/20"
        : "bg-slate-800 border border-slate-700"
    }`}
  >
    <Text
      className={`text-[10px] font-bold uppercase tracking-wider ${
        variant === "primary" ? "text-primary" : "text-slate-400"
      }`}
    >
      {label}
    </Text>
  </View>
);

export function AdminHubAgentsScreen() {
  const router = useRouter();
  const { isReady, isAdmin } = useRequireAdmin();

  const { data, isError, error, isLoading, isRefetching, refetch } = useQuery({
    queryKey: queryKeys.admin.hubAgents(),
    queryFn: () => listHubAgentsAdmin(1, 200),
    enabled: isReady && isAdmin,
  });

  const items = data?.items ?? [];
  const errorMessage =
    error instanceof Error ? error.message : "Could not load shared agents.";

  const enabledCount = useMemo(
    () => items.filter((item) => item.enabled).length,
    [items],
  );

  if (!isReady || (isLoading && !isRefetching)) {
    return <FullscreenLoader message="Loading shared agents..." />;
  }
  if (!isAdmin) {
    return null;
  }

  return (
    <ScreenContainer>
      <PageHeader
        title="Shared Agents"
        subtitle="Global service directory."
        rightElement={
          <View className="flex-row gap-2">
            <IconButton
              accessibilityLabel="Add shared agent"
              icon="add"
              size="sm"
              onPress={() => {
                blurActiveElement();
                router.push("/admin/hub-a2a/new");
              }}
            />
            <IconButton
              accessibilityLabel="Go back"
              icon="chevron-back"
              size="sm"
              variant="secondary"
              onPress={() => {
                blurActiveElement();
                if (router.canGoBack()) {
                  router.back();
                } else {
                  router.replace("/admin");
                }
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
            refreshing={isRefetching}
            onRefresh={refetch}
            tintColor="#FFFFFF"
            colors={["#FFFFFF"]}
          />
        }
      >
        <View className="flex-row items-center justify-between mb-4">
          <Text className="text-[10px] font-bold text-slate-500 uppercase">
            {enabledCount}/{items.length} enabled
          </Text>
          <Button
            label="Refresh"
            size="xs"
            variant="secondary"
            iconLeft="refresh-outline"
            onPress={() => refetch()}
          />
        </View>

        {isError ? (
          <View className="mt-4 rounded-2xl bg-red-500/10 p-6 border border-red-500/20">
            <Text className="text-base font-bold text-red-200">
              Load shared agents failed
            </Text>
            <Text className="mt-2 text-sm font-medium text-red-100/90">
              {errorMessage}
            </Text>
            <Button
              className="mt-4 self-start"
              label="Retry"
              size="sm"
              variant="primary"
              onPress={() => refetch()}
            />
          </View>
        ) : null}

        {!isError && items.length === 0 ? (
          <View className="mt-4 rounded-2xl bg-surface p-6">
            <Text className="text-base font-bold text-white">
              No shared agents
            </Text>
            <Text className="mt-2 text-sm font-medium text-slate-400">
              Create a shared agent to make it available to users.
            </Text>
          </View>
        ) : (
          items.map((agent) => (
            <View
              key={agent.id}
              className="mb-4 rounded-2xl bg-surface overflow-hidden"
            >
              <Pressable
                className="p-5"
                onPress={() => {
                  blurActiveElement();
                  router.push(`/admin/hub-a2a/${agent.id}`);
                }}
                accessibilityRole="button"
                accessibilityLabel={`Edit ${agent.name}`}
              >
                <View className="flex-row items-start justify-between">
                  <View className="flex-1 pr-4">
                    <Text
                      className="text-lg font-bold text-white"
                      numberOfLines={1}
                    >
                      {agent.name}
                    </Text>
                    <Text
                      className="mt-1 break-all text-xs font-medium text-slate-500"
                      numberOfLines={1}
                    >
                      {agent.card_url}
                    </Text>

                    <View className="mt-4 flex-row flex-wrap gap-2">
                      {pill(
                        agent.availability_policy === "public"
                          ? "Public"
                          : "Allowlist",
                        agent.availability_policy === "public"
                          ? "primary"
                          : "muted",
                      )}
                      {pill(
                        agent.enabled ? "Enabled" : "Disabled",
                        agent.enabled ? "primary" : "muted",
                      )}
                      {agent.has_credential
                        ? pill(
                            agent.token_last4
                              ? `****${agent.token_last4}`
                              : "Configured",
                            "muted",
                          )
                        : pill("No Cred", "muted")}
                    </View>
                  </View>
                  <Ionicons name="chevron-forward" size={18} color="#475569" />
                </View>
              </Pressable>

              {agent.availability_policy === "allowlist" ? (
                <View className="bg-black/30 px-5 py-3">
                  <Button
                    label="Manage Allowlist"
                    size="sm"
                    variant="secondary"
                    iconLeft="people-outline"
                    onPress={() => {
                      blurActiveElement();
                      router.push(`/admin/hub-a2a/allowlist/${agent.id}`);
                    }}
                  />
                </View>
              ) : null}
            </View>
          ))
        )}
      </ScrollView>
    </ScreenContainer>
  );
}
