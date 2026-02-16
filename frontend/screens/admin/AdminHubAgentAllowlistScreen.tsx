import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { usePreventRemoveWhenDirty } from "@/hooks/usePreventRemoveWhenDirty";
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
  buildNewAllowlistDraftEntry,
  deriveAllowlistChanges,
  hasAllowlistEmail,
  type HubAgentAllowlistDraftEntry,
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

  const [draftEntries, setDraftEntries] = useState<
    HubAgentAllowlistDraftEntry[]
  >([]);
  const [baseEntries, setBaseEntries] = useState<
    HubA2AAllowlistEntryResponse[]
  >([]);
  const [allowlistEmail, setAllowlistEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const initializedRef = useRef(false);

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

  const changes = useMemo(
    () => deriveAllowlistChanges(baseEntries, draftEntries),
    [baseEntries, draftEntries],
  );
  const dirty =
    changes.addEmails.length > 0 || changes.removeEntryIds.length > 0;
  const { allowNextNavigation } = usePreventRemoveWhenDirty({ dirty });

  useEffect(() => {
    initializedRef.current = false;
  }, [agentId]);

  useEffect(() => {
    if (!allowlistQuery.data?.items) return;
    if (!initializedRef.current) {
      initializedRef.current = true;
      setBaseEntries(allowlistQuery.data.items);
      setDraftEntries(
        buildAllowlistDraftFromEntries(allowlistQuery.data.items),
      );
      return;
    }
    if (dirty) return;
    setBaseEntries(allowlistQuery.data.items);
    setDraftEntries(buildAllowlistDraftFromEntries(allowlistQuery.data.items));
  }, [allowlistQuery.data?.items, dirty]);

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
    const allowlistResult = await allowlistQuery.refetch();
    if (!allowlistResult.data || dirty) return;
    setBaseEntries(allowlistResult.data.items);
    setDraftEntries(buildAllowlistDraftFromEntries(allowlistResult.data.items));
  }, [agentId, agentQuery, allowlistQuery, dirty]);

  const handleAddDraftEmail = useCallback(() => {
    const trimmed = allowlistEmail.trim().toLowerCase();
    if (!trimmed) return;
    if (hasAllowlistEmail(draftEntries, trimmed)) {
      toast.error("Validation failed", "This email is already in allowlist.");
      return;
    }
    setDraftEntries((current) => [
      ...current,
      buildNewAllowlistDraftEntry(trimmed, `${Date.now()}`),
    ]);
    setAllowlistEmail("");
  }, [allowlistEmail, draftEntries]);

  const handleRemoveDraftEntry = useCallback((entryId: string) => {
    setDraftEntries((current) =>
      current.filter((entry) => entry.id !== entryId),
    );
  }, []);

  const handleSave = useCallback(async () => {
    if (saving) return;
    blurActiveElement();
    if (!dirty) {
      allowNextNavigation();
      router.replace("/admin/hub-a2a");
      return;
    }

    setSaving(true);
    try {
      for (const email of changes.addEmails) {
        await addHubAgentAllowlistAdmin(agentId, { email });
      }
      for (const entryId of changes.removeEntryIds) {
        await deleteHubAgentAllowlistEntryAdmin(agentId, entryId);
      }
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.hubAgentAllowlist(agentId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.hubAgents(),
      });
      toast.success(
        "Allowlist saved",
        `${changes.addEmails.length + changes.removeEntryIds.length} changes applied.`,
      );
      allowNextNavigation();
      router.replace("/admin/hub-a2a");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Save failed.";
      toast.error("Save failed", message);
    } finally {
      setSaving(false);
    }
  }, [
    agentId,
    allowNextNavigation,
    changes.addEmails,
    changes.removeEntryIds,
    dirty,
    queryClient,
    router,
    saving,
  ]);

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
              onPress={handleAddDraftEmail}
              disabled={!allowlistEmail.trim()}
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
                  <View className="flex-row items-center gap-2">
                    <Text
                      className="text-sm font-semibold text-white"
                      numberOfLines={1}
                    >
                      {entry.userLabel}
                    </Text>
                    {entry.existingId == null ? (
                      <View className="rounded-full bg-emerald-500/20 px-2 py-0.5">
                        <Text className="text-[10px] font-semibold text-emerald-200">
                          NEW
                        </Text>
                      </View>
                    ) : null}
                  </View>
                  {entry.userId ? (
                    <Text className="mt-1 text-xs text-muted" numberOfLines={1}>
                      {entry.userId}
                    </Text>
                  ) : null}
                </View>
                <Pressable
                  className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
                  onPress={() => handleRemoveDraftEntry(entry.id)}
                  accessibilityRole="button"
                  accessibilityLabel="Remove allowlist entry"
                >
                  <Ionicons name="trash-outline" size={14} color="#f87171" />
                  <Text className="text-xs font-medium text-red-300">
                    Remove
                  </Text>
                </Pressable>
              </View>
            ))
          )}
        </View>

        <View className="mt-10 flex-row items-center justify-between gap-3">
          <Button
            label="Cancel"
            variant="outline"
            onPress={() => {
              blurActiveElement();
              backOrHome(router, "/admin/hub-a2a");
            }}
          />
          <Button
            label={saving ? "Saving..." : "Save"}
            onPress={handleSave}
            loading={saving}
            disabled={saving}
          />
        </View>
      </ScrollView>
    </ScreenContainer>
  );
}
