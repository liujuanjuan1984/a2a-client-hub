import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { PAGE_HEADER_CONTENT_GAP } from "@/components/layout/spacing";
import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { usePreventRemoveWhenDirty } from "@/hooks/usePreventRemoveWhenDirty";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import { createWithAdminAutoAllowlist } from "@/lib/agentCreateAllowlist";
import { createProxyAllowlistEntry } from "@/lib/api/adminProxyAllowlist";
import { createHubAgentAdmin } from "@/lib/api/hubA2aAgentsAdmin";
import { confirmAction } from "@/lib/confirm";
import { blurActiveElement } from "@/lib/focus";
import { backOrHome } from "@/lib/navigation";
import { queryKeys } from "@/lib/queryKeys";
import { toast } from "@/lib/toast";
import { HubAgentFormSections } from "@/screens/admin/HubAgentFormSections";
import { useHubAgentFormState } from "@/screens/admin/hubAgentFormState";

export function AdminHubAgentNewScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isReady, isAdmin } = useRequireAdmin();
  const [saving, setSaving] = useState(false);

  const {
    values,
    errors,
    canSave,
    hasDraftInput,
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
    validate,
    buildPayload,
  } = useHubAgentFormState();

  const { allowNextNavigation } = usePreventRemoveWhenDirty({
    dirty: hasDraftInput,
  });

  const handleSave = useCallback(async () => {
    if (saving) return;
    blurActiveElement();
    if (!validate()) return;

    setSaving(true);
    try {
      const payload = buildPayload();
      const result = await createWithAdminAutoAllowlist({
        isAdmin,
        cardUrl: payload.card_url,
        create: () => createHubAgentAdmin(payload),
        confirmAddHost: (host) =>
          confirmAction({
            title: "Host not allowlisted",
            message: `The card URL host "${host}" is not in the proxy allowlist. Add it automatically and continue creating the agent?`,
            confirmLabel: "Add and Continue",
            cancelLabel: "Exit Create",
          }),
        addHostToAllowlist: async (host) => {
          await createProxyAllowlistEntry({ host_pattern: host });
        },
        onCancelCreate: async () => {
          allowNextNavigation();
          backOrHome(router, "/admin/hub-a2a");
        },
      });
      if (result.status === "cancelled") {
        return;
      }

      const created = result.value;
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.hubAgents() });
      toast.success("Shared agent created", created.name);
      allowNextNavigation();
      router.replace("/admin/hub-a2a");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Create failed.";
      toast.error("Create failed", message);
    } finally {
      setSaving(false);
    }
  }, [
    allowNextNavigation,
    buildPayload,
    isAdmin,
    queryClient,
    router,
    saving,
    validate,
  ]);

  if (!isReady) {
    return <FullscreenLoader message="Checking permissions..." />;
  }
  if (!isAdmin) {
    return null;
  }

  return (
    <ScreenContainer>
      <PageHeader
        title="New shared agent"
        subtitle="Create an admin-managed A2A service directory entry."
        rightElement={
          <IconButton
            accessibilityLabel="Go back"
            icon="chevron-back"
            size="sm"
            variant="secondary"
            onPress={() => {
              blurActiveElement();
              backOrHome(router, "/admin/hub-a2a");
            }}
          />
        }
      />

      <ScrollView
        style={{ marginTop: PAGE_HEADER_CONTENT_GAP }}
        contentContainerStyle={{ paddingBottom: 32 }}
      >
        <HubAgentFormSections
          values={values}
          errors={errors}
          availabilityDescription="Public agents are visible to all users. Allowlist agents require an explicit user entry."
          authenticationDescription="Configure how the hub service authenticates to the upstream agent."
          tokenLabel="Token"
          tokenPlaceholder="Enter bearer token"
          extraHeadersDescription="Optional headers forwarded to the upstream agent."
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
            label={saving ? "Creating..." : "Create"}
            onPress={handleSave}
            loading={saving}
            disabled={!canSave || saving}
          />
        </View>
      </ScrollView>
    </ScreenContainer>
  );
}
