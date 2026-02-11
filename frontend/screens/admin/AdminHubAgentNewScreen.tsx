import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Pressable, ScrollView, Switch, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { Input } from "@/components/ui/Input";
import { KeyValueInputRow } from "@/components/ui/KeyValueInputRow";
import { PageHeader } from "@/components/ui/PageHeader";
import { usePreventRemoveWhenDirty } from "@/hooks/usePreventRemoveWhenDirty";
import { useRequireAdmin } from "@/hooks/useRequireAdmin";
import {
  createHubAgentAdmin,
  type HubA2AAgentAdminCreate,
  type HubA2AAuthType,
  type HubA2AAvailabilityPolicy,
} from "@/lib/api/hubA2aAgentsAdmin";
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

export function AdminHubAgentNewScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isReady, isAdmin } = useRequireAdmin();

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

  const [errors, setErrors] = useState<{ name?: string; cardUrl?: string }>({});
  const [saving, setSaving] = useState(false);

  const canSave = useMemo(
    () => Boolean(name.trim()) && Boolean(cardUrl.trim()),
    [name, cardUrl],
  );

  const dirty = useMemo(() => {
    return (
      Boolean(name.trim()) ||
      Boolean(cardUrl.trim()) ||
      tagsText.trim().length > 0 ||
      token.trim().length > 0 ||
      extraHeaders.some((row) => row.key.trim() || row.value.trim())
    );
  }, [name, cardUrl, extraHeaders, tagsText, token]);

  const { allowNextNavigation } = usePreventRemoveWhenDirty({ dirty });

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

  const buildPayload = (): HubA2AAgentAdminCreate => {
    const tags = parseTags(tagsText);
    const extra_headers = headerRowsToRecord(extraHeaders);
    const payload: HubA2AAgentAdminCreate = {
      name: name.trim(),
      card_url: cardUrl.trim(),
      availability_policy: availabilityPolicy,
      auth_type: authType,
      auth_header: authType === "bearer" ? authHeader.trim() : null,
      auth_scheme: authType === "bearer" ? authScheme.trim() : null,
      enabled,
      tags,
      extra_headers,
    };
    const trimmedToken = token.trim();
    if (trimmedToken) {
      payload.token = trimmedToken;
    }
    return payload;
  };

  const handleSave = useCallback(async () => {
    if (saving) return;
    blurActiveElement();
    if (!validate()) return;

    setSaving(true);
    try {
      const created = await createHubAgentAdmin(buildPayload());
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.hubAgents() });
      toast.success("Shared agent created", created.name);
      allowNextNavigation();
      router.replace(`/admin/hub-a2a/${created.id}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Create failed.";
      toast.error("Create failed", message);
    } finally {
      setSaving(false);
    }
  }, [
    authHeader,
    authScheme,
    authType,
    availabilityPolicy,
    cardUrl,
    enabled,
    extraHeaders,
    name,
    router,
    saving,
    tagsText,
    token,
    allowNextNavigation,
  ]);

  if (!isReady) {
    return <FullscreenLoader message="Checking permissions..." />;
  }
  if (!isAdmin) {
    return null;
  }

  return (
    <View className="flex-1 bg-background px-6 pt-8">
      <PageHeader
        title="New shared agent"
        subtitle="Create an admin-managed A2A service directory entry."
        rightElement={
          <Button
            label="Back"
            size="xs"
            variant="secondary"
            iconLeft="chevron-back"
            onPress={() => {
              blurActiveElement();
              backOrHome(router, "/admin/hub-a2a");
            }}
          />
        }
      />

      <ScrollView
        className="mt-3"
        contentContainerStyle={{ paddingBottom: 32 }}
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
          <Text className="mt-2 text-sm text-muted">
            Public agents are visible to all users. Allowlist agents require an
            explicit user entry.
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
        </View>

        <View className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/30 p-5">
          <Text className="text-base font-semibold text-white">
            Authentication
          </Text>
          <Text className="mt-2 text-sm text-muted">
            Configure how the hub service authenticates to the upstream agent.
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
                label="Token"
                placeholder="Enter bearer token"
                secureTextEntry
                value={token}
                onChangeText={setToken}
              />
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
          <Text className="mt-2 text-sm text-muted">
            Optional headers forwarded to the upstream agent.
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
    </View>
  );
}
