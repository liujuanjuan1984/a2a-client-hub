import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";

import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAsyncListLoad } from "@/hooks/useAsyncListLoad";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import {
  listHubAgentsAdmin,
  type HubA2AAgentAdminResponse,
} from "@/lib/api/hubA2aAgentsAdmin";
import { blurActiveElement } from "@/lib/focus";

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
  const { refreshing, run } = useAsyncListLoad();
  const [items, setItems] = useState<HubA2AAgentAdminResponse[]>([]);

  const load = useCallback(
    async (mode: "loading" | "refreshing" = "loading") => {
      await run(
        async () => {
          const response = await listHubAgentsAdmin(1, 200);
          setItems(response.items);
        },
        {
          mode,
          errorTitle: "Load shared agents failed",
          fallbackMessage: "Could not load shared agents.",
        },
      );
    },
    [run],
  );

  useEffect(() => {
    if (!isReady || !isAdmin) return;
    load().catch(() => {
      // Error already handled
    });
  }, [isReady, isAdmin, load]);

  const enabledCount = useMemo(
    () => items.filter((item) => item.enabled).length,
    [items],
  );

  if (!isReady) {
    return <FullscreenLoader message="Checking permissions..." />;
  }
  if (!isAdmin) {
    return null;
  }

  return (
    <View className="flex-1 bg-background px-6 pt-10">
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
        className="mt-6"
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => load("refreshing")}
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
            onPress={() => load("refreshing")}
            accessibilityRole="button"
            accessibilityLabel="Refresh"
          >
            <Ionicons name="refresh-outline" size={14} color="#94a3b8" />
            <Text className="text-xs font-medium text-slate-300">Refresh</Text>
          </Pressable>
        </View>

        {items.length === 0 ? (
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
            <Pressable
              key={agent.id}
              className="mt-4 overflow-hidden rounded-3xl border border-slate-800 bg-slate-900/30"
              onPress={() => {
                blurActiveElement();
                router.push(`/admin/hub-a2a/${agent.id}`);
              }}
              accessibilityRole="button"
              accessibilityLabel={`Edit ${agent.name}`}
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
              </View>
            </Pressable>
          ))
        )}
      </ScrollView>
    </View>
  );
}
