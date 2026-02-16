import { Ionicons } from "@expo/vector-icons";
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
    className={`self-start rounded-full px-2.5 py-1 ${
      variant === "primary" ? "bg-primary/20" : "bg-slate-800/60"
    }`}
  >
    <Text
      className={`text-[11px] font-semibold ${
        variant === "primary" ? "text-primary" : "text-slate-200"
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
        title="Shared A2A Agents"
        subtitle="Admin-managed global service directory."
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
            <Button
              label="Back"
              size="xs"
              variant="secondary"
              iconLeft="chevron-back"
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
            tintColor="#5c6afb"
            colors={["#5c6afb"]}
          />
        }
      >
        <View className="flex-row items-center justify-between">
          <Text className="text-xs text-muted">
            {enabledCount}/{items.length} enabled
          </Text>
          <Pressable
            className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
            onPress={() => refetch()}
            accessibilityRole="button"
            accessibilityLabel="Refresh"
          >
            <Ionicons name="refresh-outline" size={14} color="#94a3b8" />
            <Text className="text-xs font-medium text-slate-300">Refresh</Text>
          </Pressable>
        </View>

        {isError ? (
          <View className="mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-6">
            <Text className="text-base font-semibold text-red-200">
              Load shared agents failed
            </Text>
            <Text className="mt-2 text-sm text-red-100/90">{errorMessage}</Text>
            <Pressable
              className="mt-4 self-start rounded-lg border border-red-300/40 px-3 py-2 active:bg-red-500/20"
              onPress={() => refetch()}
              accessibilityRole="button"
              accessibilityLabel="Retry loading shared agents"
            >
              <Text className="text-xs font-semibold text-red-100">Retry</Text>
            </Pressable>
          </View>
        ) : null}

        {!isError && items.length === 0 ? (
          <View className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
            <Text className="text-base font-semibold text-white">
              No shared agents
            </Text>
            <Text className="mt-2 text-sm text-muted">
              Create a shared agent to make it available to users.
            </Text>
          </View>
        ) : (
          items.map((agent) => (
            <View
              key={agent.id}
              className="mt-4 overflow-hidden rounded-3xl border border-slate-800 bg-slate-900/30"
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
                      className="text-xl font-bold text-white"
                      numberOfLines={1}
                    >
                      {agent.name}
                    </Text>
                    <Text
                      className="mt-1 break-all text-xs text-muted"
                      numberOfLines={1}
                    >
                      {agent.card_url}
                    </Text>

                    <View className="mt-3 flex-row flex-wrap gap-2">
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
                              ? `Credential • ****${agent.token_last4}`
                              : "Credential • configured",
                            "muted",
                          )
                        : pill("Credential • none", "muted")}
                    </View>
                  </View>
                  <Ionicons name="chevron-forward" size={18} color="#94a3b8" />
                </View>
              </Pressable>

              {agent.availability_policy === "allowlist" ? (
                <View className="border-t border-slate-800/60 px-5 py-3">
                  <Pressable
                    className="self-start rounded-full border border-sky-400/40 bg-sky-500/15 px-3 py-1"
                    onPress={() => {
                      blurActiveElement();
                      router.push(`/admin/hub-a2a/allowlist/${agent.id}`);
                    }}
                    accessibilityRole="button"
                    accessibilityLabel={`Manage allowlist for ${agent.name}`}
                  >
                    <Text className="text-[11px] font-semibold text-sky-200">
                      Manage allowlist
                    </Text>
                  </Pressable>
                </View>
              ) : null}
            </View>
          ))
        )}
      </ScrollView>
    </ScreenContainer>
  );
}
