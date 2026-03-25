import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { usePreventRemoveWhenDirty } from "@/hooks/usePreventRemoveWhenDirty";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import { executeWithAdminAutoAllowlist } from "@/lib/agentCreateAllowlist";
import { createProxyAllowlistEntry } from "@/lib/api/adminProxyAllowlist";
import {
  deleteHubAgentAdmin,
  getHubAgentAdmin,
  updateHubAgentAdmin,
  type HubA2AAgentAdminResponse,
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
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const hasShownAgentLoadErrorRef = useRef(false);
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

  const refreshing = agentQuery.isRefetching;

  const dirty = useMemo(() => {
    if (!agent) return false;
    return (
      JSON.stringify(comparablePayload) !==
      JSON.stringify(buildHubAgentComparablePayloadFromRecord(agent))
    );
  }, [agent, comparablePayload]);

  const { allowNextNavigation } = usePreventRemoveWhenDirty({ dirty });

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

  const refresh = useCallback(async () => {
    if (!agentId) return;

    const agentResult = await agentQuery.refetch();
    if (agentResult.data) {
      setAgent(agentResult.data);
      hydrateFromRecord(agentResult.data);
      formInitializedRef.current = true;
    }
  }, [agentId, agentQuery.refetch, hydrateFromRecord]);

  const handleSave = useCallback(async () => {
    if (!agentId || saving) return;
    blurActiveElement();
    if (!validate()) return;

    setSaving(true);
    try {
      const payload = buildPayload();
      const result = await executeWithAdminAutoAllowlist({
        isAdmin,
        cardUrl: payload.card_url,
        run: () => updateHubAgentAdmin(agentId, payload),
        confirmAddHost: (host) =>
          confirmAction({
            title: "Host not allowlisted",
            message: `The card URL host "${host}" is not in the proxy allowlist. Add it automatically and continue saving the shared agent?`,
            confirmLabel: "Add and Continue",
            cancelLabel: "Keep Editing",
          }),
        addHostToAllowlist: async (host) => {
          await createProxyAllowlistEntry({ host_pattern: host });
        },
        onCancel: async () => undefined,
      });
      if (result.status === "cancelled") {
        return;
      }
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.hubAgents(),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.hubAgent(agentId),
      });
      toast.success("Saved", "Shared agent updated.");
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
    buildPayload,
    isAdmin,
    queryClient,
    router,
    saving,
    validate,
  ]);

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
            <IconButton
              accessibilityLabel="Go back"
              icon="chevron-back"
              size="sm"
              variant="secondary"
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
        subtitle="Update directory entry and credentials."
        rightElement={
          <IconButton
            accessibilityLabel="Go back"
            icon="chevron-back"
            size="sm"
            variant="secondary"
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
            <Button
              className="self-start"
              label="Manage allowlist"
              size="sm"
              variant="secondary"
              onPress={() => {
                blurActiveElement();
                router.push(`/admin/hub-a2a/allowlist/${agentId}`);
              }}
            />
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
