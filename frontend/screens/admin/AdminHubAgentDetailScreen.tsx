import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  Switch,
  Text,
  View,
} from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { Input } from "@/components/ui/Input";
import { KeyValueInputRow } from "@/components/ui/KeyValueInputRow";
import { PageHeader } from "@/components/ui/PageHeader";
import { useAsyncListLoad } from "@/hooks/useAsyncListLoad";
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
  type HubA2AAuthType,
  type HubA2AAvailabilityPolicy,
  type HubA2AAgentAdminUpdate,
} from "@/lib/api/hubA2aAgentsAdmin";
import { confirmAction } from "@/lib/confirm";
import { blurActiveElement } from "@/lib/focus";
import { generateId } from "@/lib/id";
import { backOrHome } from "@/lib/navigation";
import { queryKeys } from "@/lib/queryKeys";
import { toast } from "@/lib/toast";
import {
  type HeaderRow,
  headerRowsToRecord,
  parseTags,
  recordToHeaderRows,
  validateHttpUrl,
} from "@/screens/admin/hubAgentFormUtils";

const authTypes: { label: string; value: HubA2AAuthType }[] = [
  { label: "No Auth", value: "none" },
  { label: "Bearer", value: "bearer" },
];

const policies: { label: string; value: HubA2AAvailabilityPolicy }[] = [
  { label: "Public", value: "public" },
  { label: "Allowlist", value: "allowlist" },
];

type AdminHubAgentDetailScreenProps = {
  agentId: string;
};

export function AdminHubAgentDetailScreen({
  agentId,
}: AdminHubAgentDetailScreenProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isReady, isAdmin } = useRequireAdmin();
  const { loading, refreshing, run } = useAsyncListLoad();

  const [agent, setAgent] = useState<HubA2AAgentAdminResponse | null>(null);
  const [allowlist, setAllowlist] = useState<HubA2AAllowlistEntryResponse[]>(
    [],
  );
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Editable fields
  const [name, setName] = useState("");
  const [cardUrl, setCardUrl] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [availabilityPolicy, setAvailabilityPolicy] =
    useState<HubA2AAvailabilityPolicy>("public");
  const [authType, setAuthType] = useState<HubA2AAuthType>("none");
  const [authHeader, setAuthHeader] = useState("Authorization");
  const [authScheme, setAuthScheme] = useState("Bearer");
  const [token, setToken] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [extraHeaders, setExtraHeaders] = useState<HeaderRow[]>(
    recordToHeaderRows({}),
  );

  const [allowlistEmail, setAllowlistEmail] = useState("");
  const [errors, setErrors] = useState<{ name?: string; cardUrl?: string }>({});

  const canSave = useMemo(
    () => Boolean(name.trim()) && Boolean(cardUrl.trim()),
    [name, cardUrl],
  );

  const dirty = useMemo(() => {
    if (!agent) return false;
    const current = {
      name: name.trim(),
      card_url: cardUrl.trim(),
      enabled,
      availability_policy: availabilityPolicy,
      auth_type: authType,
      auth_header: authType === "bearer" ? authHeader.trim() : null,
      auth_scheme: authType === "bearer" ? authScheme.trim() : null,
      tags: parseTags(tagsText),
      extra_headers: headerRowsToRecord(extraHeaders),
      // token is intentionally excluded (write-only)
    };
    const initial = {
      name: agent.name,
      card_url: agent.card_url,
      enabled: agent.enabled,
      availability_policy: agent.availability_policy,
      auth_type: agent.auth_type,
      auth_header: agent.auth_header ?? null,
      auth_scheme: agent.auth_scheme ?? null,
      tags: agent.tags ?? [],
      extra_headers: agent.extra_headers ?? {},
    };
    return JSON.stringify(current) !== JSON.stringify(initial);
  }, [
    agent,
    authHeader,
    authScheme,
    authType,
    availabilityPolicy,
    cardUrl,
    enabled,
    extraHeaders,
    name,
    tagsText,
  ]);

  usePreventRemoveWhenDirty({ dirty });

  const validate = () => {
    const nextErrors: { name?: string; cardUrl?: string } = {};
    if (!name.trim()) nextErrors.name = "Name is required.";
    if (!cardUrl.trim()) nextErrors.cardUrl = "Agent Card URL is required.";
    if (cardUrl.trim() && !validateHttpUrl(cardUrl.trim())) {
      nextErrors.cardUrl = "Please enter a valid http(s) URL.";
    }
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const hydrateFromAgent = useCallback((value: HubA2AAgentAdminResponse) => {
    setAgent(value);
    setName(value.name ?? "");
    setCardUrl(value.card_url ?? "");
    setEnabled(Boolean(value.enabled));
    setAvailabilityPolicy(value.availability_policy);
    setAuthType(value.auth_type);
    setAuthHeader(value.auth_header ?? "Authorization");
    setAuthScheme(value.auth_scheme ?? "Bearer");
    setToken("");
    setTagsText((value.tags ?? []).join(", "));
    setExtraHeaders(recordToHeaderRows(value.extra_headers ?? {}));
  }, []);

  const load = useCallback(
    async (mode: "loading" | "refreshing" = "loading") => {
      if (!agentId) return;
      await run(
        async () => {
          const fetched = await getHubAgentAdmin(agentId);
          hydrateFromAgent(fetched);
          if (fetched.availability_policy === "allowlist") {
            const list = await listHubAgentAllowlistAdmin(agentId);
            setAllowlist(list.items);
          } else {
            setAllowlist([]);
          }
        },
        {
          mode,
          errorTitle: "Load shared agent failed",
          fallbackMessage: "Could not load shared agent.",
        },
      );
    },
    [agentId, hydrateFromAgent, run],
  );

  useEffect(() => {
    if (!isReady || !isAdmin) return;
    if (!agentId) return;
    load().catch(() => {
      // Error already handled
    });
  }, [isReady, isAdmin, agentId, load]);

  const setHeaderRow = useCallback(
    (id: string, field: "key" | "value", value: string) => {
      setExtraHeaders((rows) =>
        rows.map((row) => (row.id === id ? { ...row, [field]: value } : row)),
      );
    },
    [],
  );

  const removeHeaderRow = useCallback((id: string) => {
    setExtraHeaders((rows) => {
      const next = rows.filter((row) => row.id !== id);
      return next.length ? next : recordToHeaderRows({});
    });
  }, []);

  const addHeaderRow = useCallback(() => {
    setExtraHeaders((rows) => [
      ...rows,
      { id: generateId(), key: "", value: "" },
    ]);
  }, []);

  const buildUpdatePayload = (): HubA2AAgentAdminUpdate => {
    const payload: HubA2AAgentAdminUpdate = {
      name: name.trim(),
      card_url: cardUrl.trim(),
      availability_policy: availabilityPolicy,
      auth_type: authType,
      auth_header: authType === "bearer" ? authHeader.trim() : null,
      auth_scheme: authType === "bearer" ? authScheme.trim() : null,
      enabled,
      tags: parseTags(tagsText),
      extra_headers: headerRowsToRecord(extraHeaders),
    };
    const trimmedToken = token.trim();
    if (trimmedToken) {
      payload.token = trimmedToken;
    }
    return payload;
  };

  const handleSave = useCallback(async () => {
    if (!agentId || saving) return;
    blurActiveElement();
    if (!validate()) return;

    setSaving(true);
    try {
      await updateHubAgentAdmin(agentId, buildUpdatePayload());
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.hubAgents() });
      toast.success("Saved", "Shared agent updated.");
      await load("refreshing");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Save failed.";
      toast.error("Save failed", message);
    } finally {
      setSaving(false);
    }
  }, [
    agentId,
    saving,
    authHeader,
    authScheme,
    authType,
    availabilityPolicy,
    cardUrl,
    enabled,
    extraHeaders,
    name,
    tagsText,
    token,
    load,
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
  }, [agent, agentId, deleting, router]);

  const canAddAllowlist = useMemo(
    () => availabilityPolicy === "allowlist" && Boolean(allowlistEmail.trim()),
    [availabilityPolicy, allowlistEmail],
  );

  const handleAddAllowlist = useCallback(async () => {
    if (!agentId) return;
    if (!canAddAllowlist) return;
    blurActiveElement();
    try {
      await addHubAgentAllowlistAdmin(agentId, {
        email: allowlistEmail.trim(),
      });
      setAllowlistEmail("");
      toast.success("Allowlist updated", "User added.");
      await load("refreshing");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Add failed.";
      toast.error("Add failed", message);
    }
  }, [agentId, allowlistEmail, canAddAllowlist, load]);

  const handleDeleteAllowlistEntry = useCallback(
    async (entryId: string) => {
      if (!agentId) return;
      blurActiveElement();
      try {
        await deleteHubAgentAllowlistEntryAdmin(agentId, entryId);
        toast.success("Allowlist updated", "User removed.");
        await load("refreshing");
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Remove failed.";
        toast.error("Remove failed", message);
      }
    },
    [agentId, load],
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
            onRefresh={() => load("refreshing")}
            tintColor="#5c6afb"
            colors={["#5c6afb"]}
          />
        }
      >
        <View className="rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
          <Text className="text-base font-semibold text-white">Basics</Text>
          <View className="mt-4 gap-3">
            <Input
              label="Name"
              placeholder="Agent name"
              value={name}
              onChangeText={setName}
              error={errors.name}
            />
            <Input
              label="Agent Card URL"
              placeholder="https://agent.example.com/.well-known/agent.json"
              autoCapitalize="none"
              value={cardUrl}
              onChangeText={setCardUrl}
              error={errors.cardUrl}
            />

            <View className="flex-row items-center justify-between">
              <Text className="text-sm font-medium text-white">Enabled</Text>
              <Switch
                value={enabled}
                disabled={saving}
                trackColor={{ false: "#334155", true: "#5c6afb" }}
                thumbColor={enabled ? "#ffffff" : "#e2e8f0"}
                ios_backgroundColor="#334155"
                onValueChange={setEnabled}
                accessibilityLabel={`Enabled: ${enabled ? "on" : "off"}`}
              />
            </View>
          </View>
        </View>

        <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
          <Text className="text-base font-semibold text-white">
            Availability
          </Text>
          <View className="mt-4 flex-row flex-wrap gap-2">
            {policies.map((option) => (
              <Pressable
                key={option.value}
                className={`rounded-full border px-4 py-2 ${
                  availabilityPolicy === option.value
                    ? "border-primary bg-primary/20"
                    : "border-slate-700"
                }`}
                onPress={() => setAvailabilityPolicy(option.value)}
                accessibilityRole="button"
                accessibilityLabel={option.label}
              >
                <Text className="text-xs text-white">{option.label}</Text>
              </Pressable>
            ))}
          </View>
          {availabilityPolicy === "allowlist" ? (
            <Text className="mt-3 text-xs text-muted">
              Allowlist rules are enforced at request time. Remember to keep
              this list updated.
            </Text>
          ) : null}
        </View>

        <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
          <Text className="text-base font-semibold text-white">
            Authentication
          </Text>
          <View className="mt-4 flex-row flex-wrap gap-2">
            {authTypes.map((option) => (
              <Pressable
                key={option.value}
                className={`rounded-full border px-4 py-2 ${
                  authType === option.value
                    ? "border-primary bg-primary/20"
                    : "border-slate-700"
                }`}
                onPress={() => setAuthType(option.value)}
                accessibilityRole="button"
                accessibilityLabel={option.label}
              >
                <Text className="text-xs text-white">{option.label}</Text>
              </Pressable>
            ))}
          </View>

          {authType === "bearer" ? (
            <View className="mt-4 gap-3">
              <Input
                label="Auth header"
                placeholder="Authorization"
                value={authHeader}
                onChangeText={setAuthHeader}
              />
              <Input
                label="Auth scheme"
                placeholder="Bearer"
                value={authScheme}
                onChangeText={setAuthScheme}
              />
              <Input
                label="Token (write-only)"
                placeholder="Enter new bearer token to rotate"
                secureTextEntry
                value={token}
                onChangeText={setToken}
              />
              {agent?.has_credential ? (
                <Text className="text-xs text-muted">
                  Credential is configured
                  {agent.token_last4 ? ` (****${agent.token_last4}).` : "."}
                </Text>
              ) : (
                <Text className="text-xs text-muted">
                  No credential configured.
                </Text>
              )}
            </View>
          ) : null}
        </View>

        <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
          <Text className="text-base font-semibold text-white">Metadata</Text>
          <View className="mt-4 gap-3">
            <Input
              label="Tags (comma separated)"
              placeholder="e.g., coding, internal, opencode"
              value={tagsText}
              onChangeText={setTagsText}
              autoCapitalize="none"
            />
          </View>
        </View>

        <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
          <Text className="text-base font-semibold text-white">
            Extra headers
          </Text>
          <View className="mt-4 gap-3">
            {extraHeaders.map((row) => (
              <KeyValueInputRow
                key={row.id}
                keyValue={row.key}
                valueValue={row.value}
                onChangeKey={(value) => setHeaderRow(row.id, "key", value)}
                onChangeValue={(value) => setHeaderRow(row.id, "value", value)}
                onRemove={() => removeHeaderRow(row.id)}
              />
            ))}
            <Button
              className="self-start"
              label="Add header"
              variant="outline"
              size="sm"
              onPress={addHeaderRow}
            />
          </View>
        </View>

        {availabilityPolicy === "allowlist" ? (
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
