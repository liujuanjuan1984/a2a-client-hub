import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
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
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import {
  addHubAgentAllowlistAdmin,
  deleteHubAgentAllowlistEntryAdmin,
  getHubAgentAdmin,
  listHubAgentAllowlistAdmin,
  type HubA2AAllowlistEntryResponse,
} from "@/lib/api/hubA2aAgentsAdmin";
import { blurActiveElement } from "@/lib/focus";
import { backOrHome } from "@/lib/navigation";
import { queryKeys } from "@/lib/queryKeys";
import { toast } from "@/lib/toast";
import {
  buildAllowlistDraftFromEntries,
  hasAllowlistEmail,
} from "@/screens/admin/hubAgentAllowlistState";

type AdminHubAgentAllowlistScreenProps = {
  agentId: string;
};

export function AdminHubAgentAllowlistScreen({
  agentId,
}: AdminHubAgentAllowlistScreenProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isReady, isAdmin } = useRequireAdmin();

  const [allowlistEmail, setAllowlistEmail] = useState("");
  const [mutating, setMutating] = useState(false);
  const [removingUserId, setRemovingUserId] = useState<string | null>(null);

  const agentQuery = useQuery({
    queryKey: queryKeys.admin.hubAgent(agentId),
    queryFn: () => getHubAgentAdmin(agentId),
    enabled: isReady && isAdmin && Boolean(agentId),
  });

  const allowlistQuery = useQuery({
    queryKey: queryKeys.admin.hubAgentAllowlist(agentId),
    queryFn: () => listHubAgentAllowlistAdmin(agentId),
    enabled:
      isReady &&
      isAdmin &&
      Boolean(agentId) &&
      agentQuery.data?.availability_policy === "allowlist",
  });

  const entries: HubA2AAllowlistEntryResponse[] = useMemo(
    () => allowlistQuery.data?.items ?? [],
    [allowlistQuery.data?.items],
  );
  const draftEntries = useMemo(
    () => buildAllowlistDraftFromEntries(entries),
    [entries],
  );

  const loading =
    (agentQuery.isLoading && !agentQuery.data) ||
    (allowlistQuery.isLoading && !allowlistQuery.data);
  const refreshing = agentQuery.isRefetching || allowlistQuery.isRefetching;

  const refresh = useCallback(async () => {
    if (!agentId) return;
    const agentResult = await agentQuery.refetch();
    if (agentResult.data?.availability_policy !== "allowlist") {
      return;
    }
    await allowlistQuery.refetch();
  }, [agentId, agentQuery, allowlistQuery]);

  const handleAddEmail = useCallback(async () => {
    if (mutating) return;
    const trimmed = allowlistEmail.trim().toLowerCase();
    if (!trimmed) return;
    if (hasAllowlistEmail(draftEntries, trimmed)) {
      toast.error("Validation failed", "This email is already in allowlist.");
      return;
    }
    setMutating(true);
    blurActiveElement();
    try {
      await addHubAgentAllowlistAdmin(agentId, {
        email: trimmed,
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.hubAgentAllowlist(agentId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.hubAgents(),
      });
      await allowlistQuery.refetch();
      setAllowlistEmail("");
      toast.success("Allowlist updated", "Entry added.");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Could not add entry.";
      toast.error("Update failed", message);
    } finally {
      setMutating(false);
    }
  }, [
    agentId,
    draftEntries,
    allowlistEmail,
    allowlistQuery,
    mutating,
    queryClient,
  ]);

  const handleRemoveEntry = useCallback(
    async (userId: string) => {
      if (mutating || removingUserId) return;
      setMutating(true);
      setRemovingUserId(userId);
      blurActiveElement();
      try {
        await deleteHubAgentAllowlistEntryAdmin(agentId, userId);
        await queryClient.invalidateQueries({
          queryKey: queryKeys.admin.hubAgentAllowlist(agentId),
        });
        await queryClient.invalidateQueries({
          queryKey: queryKeys.admin.hubAgents(),
        });
        await allowlistQuery.refetch();
        toast.success("Allowlist updated", "Entry removed.");
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Could not remove entry.";
        toast.error("Update failed", message);
      } finally {
        setRemovingUserId(null);
        setMutating(false);
      }
    },
    [agentId, allowlistQuery, mutating, queryClient, removingUserId],
  );

  if (!isReady) {
    return <FullscreenLoader message="Checking permissions..." />;
  }
  if (!isAdmin) {
    return null;
  }
  if (!agentId) {
    return (
      <ScreenContainer>
        <PageHeader
          title="Allowlist"
          subtitle="Missing agent id."
          rightElement={
            <Button
              label="Back"
              size="xs"
              variant="secondary"
              iconLeft="chevron-back"
              onPress={() => backOrHome(router, "/admin/hub-a2a")}
            />
          }
        />
      </ScreenContainer>
    );
  }

  if (loading) {
    return <FullscreenLoader message="Loading allowlist..." />;
  }

  if (agentQuery.isError) {
    const message =
      agentQuery.error instanceof Error
        ? agentQuery.error.message
        : "Could not load shared agent.";
    return (
      <ScreenContainer>
        <PageHeader
          title="Allowlist"
          subtitle="Shared agent"
          rightElement={
            <Button
              label="Back"
              size="xs"
              variant="secondary"
              iconLeft="chevron-back"
              onPress={() => backOrHome(router, "/admin/hub-a2a")}
            />
          }
        />
        <View className="mt-6 rounded-2xl border border-red-500/30 bg-red-500/10 p-6">
          <Text className="text-base font-semibold text-red-200">
            Load shared agent failed
          </Text>
          <Text className="mt-2 text-sm text-red-100/90">{message}</Text>
          <Button
            className="mt-4 self-start"
            label="Retry"
            size="sm"
            variant="secondary"
            onPress={() => {
              refresh().catch(() => undefined);
            }}
          />
        </View>
      </ScreenContainer>
    );
  }

  if (agentQuery.data?.availability_policy !== "allowlist") {
    return (
      <ScreenContainer>
        <PageHeader
          title="Allowlist"
          subtitle={agentQuery.data?.name ?? "Shared agent"}
          rightElement={
            <Button
              label="Back"
              size="xs"
              variant="secondary"
              iconLeft="chevron-back"
              onPress={() => backOrHome(router, "/admin/hub-a2a")}
            />
          }
        />
        <View className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
          <Text className="text-base font-semibold text-white">
            Allowlist is disabled
          </Text>
          <Text className="mt-2 text-sm text-muted">
            This shared agent is not using allowlist policy.
          </Text>
        </View>
      </ScreenContainer>
    );
  }

  if (allowlistQuery.isError) {
    const message =
      allowlistQuery.error instanceof Error
        ? allowlistQuery.error.message
        : "Could not load allowlist.";
    return (
      <ScreenContainer>
        <PageHeader
          title="Allowlist"
          subtitle={agentQuery.data?.name ?? "Shared agent"}
          rightElement={
            <Button
              label="Back"
              size="xs"
              variant="secondary"
              iconLeft="chevron-back"
              onPress={() => backOrHome(router, "/admin/hub-a2a")}
            />
          }
        />
        <View className="mt-6 rounded-2xl border border-red-500/30 bg-red-500/10 p-6">
          <Text className="text-base font-semibold text-red-200">
            Load allowlist failed
          </Text>
          <Text className="mt-2 text-sm text-red-100/90">{message}</Text>
          <Button
            className="mt-4 self-start"
            label="Retry"
            size="sm"
            variant="secondary"
            onPress={() => {
              refresh().catch(() => undefined);
            }}
          />
        </View>
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer>
      <PageHeader
        title="Allowlist"
        subtitle={agentQuery.data?.name ?? "Shared agent"}
        rightElement={
          <Button
            label="Back"
            size="xs"
            variant="secondary"
            iconLeft="chevron-back"
            onPress={() => backOrHome(router, "/admin/hub-a2a")}
          />
        }
      />

      <ScrollView
        style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => refresh()}
            tintColor="#5c6afb"
            colors={["#5c6afb"]}
          />
        }
      >
        <View className="rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
          <Text className="text-base font-semibold text-white">
            Manage allowlist
          </Text>
          <Text className="mt-2 text-sm text-muted">
            Only users in this list can access the agent.
          </Text>

          <View className="mt-4 flex-row items-end gap-3">
            <View className="flex-1">
              <Input
                label="User email"
                placeholder="user@example.com"
                autoCapitalize="none"
                keyboardType="email-address"
                value={allowlistEmail}
                onChangeText={setAllowlistEmail}
              />
            </View>
            <Button
              label="Add"
              size="sm"
              onPress={() => {
                handleAddEmail().catch(() => undefined);
              }}
              disabled={!allowlistEmail.trim() || mutating}
              loading={mutating && !removingUserId}
            />
          </View>

          {draftEntries.length === 0 ? (
            <View className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/30 p-4">
              <Text className="text-sm text-muted">No allowlist entries.</Text>
            </View>
          ) : (
            draftEntries.map((entry) => (
              <View
                key={entry.id}
                className="mt-3 flex-row items-center justify-between rounded-2xl border border-slate-800 bg-slate-900/20 p-4"
              >
                <View className="flex-1 pr-3">
                  <Text
                    className="text-sm font-semibold text-white"
                    numberOfLines={1}
                  >
                    {entry.userLabel}
                  </Text>
                  {entry.userId ? (
                    <Text className="mt-1 text-xs text-muted" numberOfLines={1}>
                      {entry.userId}
                    </Text>
                  ) : null}
                </View>
                <Pressable
                  className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
                  onPress={() => {
                    handleRemoveEntry(entry.userId).catch(() => undefined);
                  }}
                  disabled={mutating}
                  style={{ opacity: mutating ? 0.5 : 1 }}
                  accessibilityRole="button"
                  accessibilityLabel="Remove allowlist entry"
                >
                  <Ionicons name="trash-outline" size={14} color="#f87171" />
                  <Text className="text-xs font-medium text-red-300">
                    {removingUserId === entry.userId ? "Removing..." : "Remove"}
                  </Text>
                </Pressable>
              </View>
            ))
          )}
        </View>
      </ScrollView>
    </ScreenContainer>
  );
}
