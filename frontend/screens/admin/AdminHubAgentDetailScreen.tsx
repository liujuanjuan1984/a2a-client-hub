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
import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { usePreventRemoveWhenDirty } from "@/hooks/usePreventRemoveWhenDirty";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import {
  addHubAgentAllowlistAdmin,
  deleteHubAgentAdmin,
  deleteHubAgentAllowlistEntryAdmin,
  getHubAgentAdmin,
  listHubAgentAllowlistAdmin,
  updateHubAgentAdmin,
  type HubA2AAgentAdminResponse,
  type HubA2AAllowlistEntryResponse,
} from "@/lib/api/hubA2aAgentsAdmin";
import { confirmAction } from "@/lib/confirm";
import { blurActiveElement } from "@/lib/focus";
import { backOrHome } from "@/lib/navigation";
import { queryKeys } from "@/lib/queryKeys";
import { toast } from "@/lib/toast";
import { HubAgentFormSections } from "@/screens/admin/HubAgentFormSections";
import {
  buildHubAgentComparablePayloadFromRecord,
  useHubAgentFormState,
} from "@/screens/admin/hubAgentFormState";

type AdminHubAgentDetailScreenProps = {
  agentId: string;
};

export function AdminHubAgentDetailScreen({
  agentId,
}: AdminHubAgentDetailScreenProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isReady, isAdmin } = useRequireAdmin();

  const [agent, setAgent] = useState<HubA2AAgentAdminResponse | null>(null);
  const [allowlist, setAllowlist] = useState<HubA2AAllowlistEntryResponse[]>(
    [],
  );
  const [allowlistEmail, setAllowlistEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const hasShownAgentLoadErrorRef = useRef(false);
  const hasShownAllowlistLoadErrorRef = useRef(false);
  const formInitializedRef = useRef(false);

  const {
    values,
    canSave,
    comparablePayload,
    setName,
    setCardUrl,
    setEnabled,
    setAvailabilityPolicy,
    setAuthType,
    setAuthHeader,
    setAuthScheme,
    setToken,
    setTagsText,
    setHeaderRow,
    removeHeaderRow,
    addHeaderRow,
    hydrateFromRecord,
    validate,
    buildPayload,
    errors,
  } = useHubAgentFormState();

  const agentQuery = useQuery({
    queryKey: queryKeys.admin.hubAgent(agentId),
    queryFn: () => getHubAgentAdmin(agentId),
    enabled: isReady && isAdmin && Boolean(agentId),
  });

  const shouldQueryAllowlist =
    isReady &&
    isAdmin &&
    Boolean(agentId) &&
    agentQuery.data?.availability_policy === "allowlist";

  const allowlistQuery = useQuery({
    queryKey: queryKeys.admin.hubAgentAllowlist(agentId),
    queryFn: () => listHubAgentAllowlistAdmin(agentId),
    enabled: shouldQueryAllowlist,
  });

  const loading = agentQuery.isLoading && !agentQuery.data && !agent;
  const refreshing = agentQuery.isRefetching || allowlistQuery.isRefetching;

  const dirty = useMemo(() => {
    if (!agent) return false;
    return (
      JSON.stringify(comparablePayload) !==
      JSON.stringify(buildHubAgentComparablePayloadFromRecord(agent))
    );
  }, [agent, comparablePayload]);

  usePreventRemoveWhenDirty({ dirty });

  useEffect(() => {
    formInitializedRef.current = false;
  }, [agentId]);

  useEffect(() => {
    if (!agentQuery.data) {
      return;
    }

    if (!formInitializedRef.current) {
      setAgent(agentQuery.data);
      hydrateFromRecord(agentQuery.data);
      formInitializedRef.current = true;
      return;
    }

    if (dirty) {
      return;
    }
    setAgent(agentQuery.data);
    hydrateFromRecord(agentQuery.data);
  }, [agentId, agentQuery.data, dirty, hydrateFromRecord]);

  useEffect(() => {
    if (!agentQuery.isError || !agentQuery.error) {
      hasShownAgentLoadErrorRef.current = false;
      return;
    }
    if (hasShownAgentLoadErrorRef.current) {
      return;
    }
    hasShownAgentLoadErrorRef.current = true;
    const message =
      agentQuery.error instanceof Error
        ? agentQuery.error.message
        : "Could not load shared agent.";
    toast.error("Load shared agent failed", message);
  }, [agentQuery.error, agentQuery.isError]);

  useEffect(() => {
    if (!allowlistQuery.data) {
      return;
    }
    setAllowlist(allowlistQuery.data.items);
  }, [allowlistQuery.data]);

  useEffect(() => {
    if (agentQuery.data?.availability_policy === "allowlist") {
      return;
    }
    setAllowlist([]);
  }, [agentQuery.data?.availability_policy]);

  useEffect(() => {
    if (
      !allowlistQuery.isError ||
      !allowlistQuery.error ||
      !shouldQueryAllowlist
    ) {
      hasShownAllowlistLoadErrorRef.current = false;
      return;
    }
    if (hasShownAllowlistLoadErrorRef.current) {
      return;
    }
    hasShownAllowlistLoadErrorRef.current = true;
    const message =
      allowlistQuery.error instanceof Error
        ? allowlistQuery.error.message
        : "Could not load allowlist.";
    toast.error("Load allowlist failed", message);
  }, [allowlistQuery.error, allowlistQuery.isError, shouldQueryAllowlist]);

  const refresh = useCallback(async () => {
    if (!agentId) return;

    const agentResult = await agentQuery.refetch();
    if (agentResult.data) {
      setAgent(agentResult.data);
      hydrateFromRecord(agentResult.data);
      formInitializedRef.current = true;
    }

    if (agentResult.data?.availability_policy === "allowlist") {
      await allowlistQuery.refetch();
      return;
    }
    setAllowlist([]);
  }, [agentId, agentQuery.refetch, allowlistQuery.refetch, hydrateFromRecord]);

  const handleSave = useCallback(async () => {
    if (!agentId || saving) return;
    blurActiveElement();
    if (!validate()) return;

    setSaving(true);
    try {
      await updateHubAgentAdmin(agentId, buildPayload());
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.hubAgents() });
      toast.success("Saved", "Shared agent updated.");
      await refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Save failed.";
      toast.error("Save failed", message);
    } finally {
      setSaving(false);
    }
  }, [agentId, buildPayload, queryClient, refresh, saving, validate]);

  const handleDelete = useCallback(async () => {
    if (!agentId || deleting || !agent) return;
    blurActiveElement();
    const confirmed = await confirmAction({
      title: "Delete shared agent",
      message: `Are you sure you want to delete ${agent.name}? This cannot be undone.`,
      confirmLabel: "Delete",
      isDestructive: true,
    });
    if (!confirmed) return;

    setDeleting(true);
    try {
      await deleteHubAgentAdmin(agentId);
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.hubAgents() });
      toast.success("Deleted", `${agent.name} has been removed.`);
      router.replace("/admin/hub-a2a");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Delete failed.";
      toast.error("Delete failed", message);
    } finally {
      setDeleting(false);
    }
  }, [agent, agentId, deleting, queryClient, router]);

  const canAddAllowlist = useMemo(
    () =>
      values.availabilityPolicy === "allowlist" &&
      Boolean(allowlistEmail.trim()),
    [allowlistEmail, values.availabilityPolicy],
  );

  const handleAddAllowlist = useCallback(async () => {
    if (!agentId || !canAddAllowlist) return;
    blurActiveElement();
    try {
      await addHubAgentAllowlistAdmin(agentId, {
        email: allowlistEmail.trim(),
      });
      setAllowlistEmail("");
      toast.success("Allowlist updated", "User added.");
      await refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Add failed.";
      toast.error("Add failed", message);
    }
  }, [agentId, allowlistEmail, canAddAllowlist, refresh]);

  const handleDeleteAllowlistEntry = useCallback(
    async (entryId: string) => {
      if (!agentId) return;
      blurActiveElement();
      try {
        await deleteHubAgentAllowlistEntryAdmin(agentId, entryId);
        toast.success("Allowlist updated", "User removed.");
        await refresh();
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Remove failed.";
        toast.error("Remove failed", message);
      }
    },
    [agentId, refresh],
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
          title="Shared agent"
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

  const tokenFootnote =
    agent?.has_credential && values.authType === "bearer" ? (
      <Text className="text-xs text-muted">
        Credential is configured
        {agent.token_last4 ? ` (****${agent.token_last4}).` : "."}
      </Text>
    ) : values.authType === "bearer" ? (
      <Text className="text-xs text-muted">No credential configured.</Text>
    ) : null;

  return (
    <ScreenContainer>
      <PageHeader
        title="Shared agent"
        subtitle="Update directory entry, credentials, and allowlists."
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
        className="mt-2"
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
        <HubAgentFormSections
          values={values}
          errors={errors}
          disableEnabledToggle={saving}
          availabilityHintWhenAllowlist="Allowlist rules are enforced at request time. Remember to keep this list updated."
          tokenLabel="Token (write-only)"
          tokenPlaceholder="Enter new bearer token to rotate"
          tokenFootnote={tokenFootnote}
          onNameChange={setName}
          onCardUrlChange={setCardUrl}
          onEnabledChange={setEnabled}
          onAvailabilityPolicyChange={setAvailabilityPolicy}
          onAuthTypeChange={setAuthType}
          onAuthHeaderChange={setAuthHeader}
          onAuthSchemeChange={setAuthScheme}
          onTokenChange={setToken}
          onTagsTextChange={setTagsText}
          onHeaderRowChange={setHeaderRow}
          onHeaderRowRemove={removeHeaderRow}
          onHeaderRowAdd={addHeaderRow}
        />

        {values.availabilityPolicy === "allowlist" ? (
          <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
            <Text className="text-base font-semibold text-white">
              Allowlist
            </Text>
            <Text className="mt-2 text-sm text-muted">
              Only users in the allowlist can access this agent.
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
                onPress={handleAddAllowlist}
                disabled={!canAddAllowlist || loading}
                loading={loading}
              />
            </View>

            {allowlist.length === 0 ? (
              <View className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/30 p-4">
                <Text className="text-sm text-muted">
                  No allowlist entries.
                </Text>
              </View>
            ) : (
              allowlist.map((entry) => (
                <View
                  key={entry.id}
                  className="mt-3 flex-row items-center justify-between rounded-2xl border border-slate-800 bg-slate-900/20 p-4"
                >
                  <View className="flex-1 pr-3">
                    <Text
                      className="text-sm font-semibold text-white"
                      numberOfLines={1}
                    >
                      {entry.user_email ?? entry.user_name ?? entry.user_id}
                    </Text>
                    <Text className="mt-1 text-xs text-muted" numberOfLines={1}>
                      {entry.user_id}
                    </Text>
                  </View>
                  <Pressable
                    className="flex-row items-center gap-1 rounded-lg px-3 py-2 active:bg-slate-800/40"
                    onPress={() => handleDeleteAllowlistEntry(entry.id)}
                    accessibilityRole="button"
                    accessibilityLabel="Remove from allowlist"
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
        ) : null}

        <View className="mt-10 flex-row items-center justify-between gap-3">
          <Button
            label="Delete"
            variant="danger"
            onPress={handleDelete}
            loading={deleting}
            disabled={deleting}
          />
          <Button
            label={saving ? "Saving..." : "Save"}
            onPress={handleSave}
            loading={saving}
            disabled={!canSave || saving}
          />
        </View>

        <View className="h-8" />
      </ScrollView>
    </ScreenContainer>
  );
}
