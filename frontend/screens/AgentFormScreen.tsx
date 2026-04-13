import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { ScreenScrollView } from "@/components/layout/ScreenScrollView";
import { BackButton } from "@/components/ui/BackButton";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { Input } from "@/components/ui/Input";
import { KeyValueInputRow } from "@/components/ui/KeyValueInputRow";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  useAgentsCatalogQuery,
  useCreateAgentMutation,
  useDeleteAgentMutation,
  useUpdateAgentMutation,
  useValidateAgentMutation,
} from "@/hooks/useAgentsCatalogQuery";
import { usePreventRemoveWhenDirty } from "@/hooks/usePreventRemoveWhenDirty";
import { type AgentAuthType } from "@/lib/agentAuth";
import { AGENT_ERROR_MESSAGES } from "@/lib/agentCatalogCache";
import { executeWithAdminAutoAllowlist } from "@/lib/agentCreateAllowlist";
import { DEFAULT_API_KEY_HEADER } from "@/lib/agentHeaders";
import { createProxyAllowlistEntry } from "@/lib/api/adminProxyAllowlist";
import {
  deleteHubAgentCredential,
  getHubAgentCredentialStatus,
  upsertHubAgentCredential,
} from "@/lib/api/hubA2aAgentsUser";
import { confirmAction } from "@/lib/confirm";
import { blurActiveElement } from "@/lib/focus";
import { isValidHttpUrl } from "@/lib/httpUrl";
import {
  appendKeyValueRow,
  ensureKeyValueRows,
  removeKeyValueRow,
  trimKeyValueRows,
  updateKeyValueRows,
} from "@/lib/keyValueRows";
import { backOrHome } from "@/lib/navigation";
import { queryKeys } from "@/lib/queryKeys";
import { toast } from "@/lib/toast";
import { type AgentHeader } from "@/store/agents";
import { useSessionStore } from "@/store/session";

const authTypes: { label: string; value: AgentAuthType }[] = [
  { label: "No Auth", value: "none" },
  { label: "Bearer", value: "bearer" },
  { label: "API Key", value: "api_key" },
  { label: "Basic", value: "basic" },
];

type AgentFormScreenProps = {
  agentId?: string;
};

type Snapshot = {
  name: string;
  cardUrl: string;
  authType: AgentAuthType;
  bearerToken: string;
  apiKeyHeader: string;
  apiKeyValue: string;
  basicUsername: string;
  basicPassword: string;
  extraHeaders: { key: string; value: string }[];
  invokeMetadataDefaults: { key: string; value: string }[];
};

const buildSnapshot = (value: {
  name: string;
  cardUrl: string;
  authType: AgentAuthType;
  bearerToken: string;
  apiKeyHeader: string;
  apiKeyValue: string;
  basicUsername: string;
  basicPassword: string;
  extraHeaders: AgentHeader[];
  invokeMetadataDefaults: AgentHeader[];
}): Snapshot => ({
  name: value.name.trim(),
  cardUrl: value.cardUrl.trim(),
  authType: value.authType,
  bearerToken: value.bearerToken.trim(),
  apiKeyHeader: value.apiKeyHeader.trim(),
  apiKeyValue: value.apiKeyValue.trim(),
  basicUsername: value.basicUsername.trim(),
  basicPassword: value.basicPassword.trim(),
  extraHeaders: trimKeyValueRows(value.extraHeaders),
  invokeMetadataDefaults: trimKeyValueRows(value.invokeMetadataDefaults),
});

export function AgentFormScreen({ agentId }: AgentFormScreenProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const isAdmin = Boolean(useSessionStore((state) => state.user?.is_superuser));
  const { data: agents = [], isFetched: hasFetchedAgents } =
    useAgentsCatalogQuery(true);
  const createAgentMutation = useCreateAgentMutation();
  const updateAgentMutation = useUpdateAgentMutation();
  const deleteAgentMutation = useDeleteAgentMutation();
  const validateAgentMutation = useValidateAgentMutation();

  const agent = useMemo(
    () => agents.find((item) => item.id === agentId),
    [agents, agentId],
  );

  const [name, setName] = useState(agent?.name ?? "");
  const [cardUrl, setCardUrl] = useState(agent?.cardUrl ?? "");
  const [authType, setAuthType] = useState<AgentAuthType>(
    agent?.authType ?? "none",
  );
  const [bearerToken, setBearerToken] = useState(agent?.bearerToken ?? "");
  const [apiKeyHeader, setApiKeyHeader] = useState(
    agent?.apiKeyHeader ?? DEFAULT_API_KEY_HEADER,
  );
  const [apiKeyValue, setApiKeyValue] = useState(agent?.apiKeyValue ?? "");
  const [basicUsername, setBasicUsername] = useState(
    agent?.basicUsername ?? "",
  );
  const [basicPassword, setBasicPassword] = useState(
    agent?.basicPassword ?? "",
  );
  const [extraHeaders, setExtraHeaders] = useState<AgentHeader[]>(
    ensureKeyValueRows(agent?.extraHeaders ?? []),
  );
  const [invokeMetadataDefaults, setInvokeMetadataDefaults] = useState<
    AgentHeader[]
  >(ensureKeyValueRows(agent?.invokeMetadataDefaults ?? []));
  const [errors, setErrors] = useState<{ name?: string; cardUrl?: string }>({});
  const [saveStatus, setSaveStatus] = useState<
    "idle" | "saving" | "success" | "error"
  >("idle");
  const [isDeleting, setIsDeleting] = useState(false);
  const [savingSharedCredential, setSavingSharedCredential] = useState(false);
  const [deletingSharedCredential, setDeletingSharedCredential] =
    useState(false);
  const [sharedToken, setSharedToken] = useState("");
  const [sharedBasicUsername, setSharedBasicUsername] = useState("");
  const [sharedBasicPassword, setSharedBasicPassword] = useState("");
  const initializedFromAgentRef = useRef(false);
  const initialSnapshotRef = useRef<Snapshot | null>(null);

  const goBackOrHome = useCallback(() => backOrHome(router), [router]);
  const isSharedAgent = Boolean(agentId && agent && agent.source === "shared");
  const isBuiltInAgent = Boolean(
    agentId && agent && agent.source === "builtin",
  );
  const sharedCredentialQuery = useQuery({
    queryKey: ["agents", "shared-credential", agentId ?? "none"],
    queryFn: () => getHubAgentCredentialStatus(agentId!),
    enabled: Boolean(isSharedAgent && agentId),
  });

  useEffect(() => {
    if (!agentId || agent) {
      return;
    }
    if (hasFetchedAgents) {
      setErrors({ name: AGENT_ERROR_MESSAGES.notFound });
    }
  }, [agentId, agent, hasFetchedAgents]);

  useEffect(() => {
    if (!agentId) {
      if (!initialSnapshotRef.current) {
        initialSnapshotRef.current = buildSnapshot({
          name,
          cardUrl,
          authType,
          bearerToken,
          apiKeyHeader,
          apiKeyValue,
          basicUsername,
          basicPassword,
          extraHeaders,
          invokeMetadataDefaults,
        });
      }
      return;
    }

    if (!agent) return;
    if (initializedFromAgentRef.current) return;
    initializedFromAgentRef.current = true;

    setName(agent.name ?? "");
    setCardUrl(agent.cardUrl ?? "");
    setAuthType(agent.authType ?? "none");
    setBearerToken(agent.bearerToken ?? "");
    setApiKeyHeader(agent.apiKeyHeader ?? DEFAULT_API_KEY_HEADER);
    setApiKeyValue(agent.apiKeyValue ?? "");
    setBasicUsername(agent.basicUsername ?? "");
    setBasicPassword(agent.basicPassword ?? "");
    setExtraHeaders(ensureKeyValueRows(agent.extraHeaders ?? []));
    setInvokeMetadataDefaults(
      ensureKeyValueRows(agent.invokeMetadataDefaults ?? []),
    );

    initialSnapshotRef.current = buildSnapshot({
      name: agent.name ?? "",
      cardUrl: agent.cardUrl ?? "",
      authType: agent.authType ?? "none",
      bearerToken: agent.bearerToken ?? "",
      apiKeyHeader: agent.apiKeyHeader ?? DEFAULT_API_KEY_HEADER,
      apiKeyValue: agent.apiKeyValue ?? "",
      basicUsername: agent.basicUsername ?? "",
      basicPassword: agent.basicPassword ?? "",
      extraHeaders: agent.extraHeaders?.length ? agent.extraHeaders : [],
      invokeMetadataDefaults: agent.invokeMetadataDefaults?.length
        ? agent.invokeMetadataDefaults
        : [],
    });
  }, [
    agentId,
    agent,
    name,
    cardUrl,
    authType,
    bearerToken,
    apiKeyHeader,
    apiKeyValue,
    basicUsername,
    basicPassword,
    extraHeaders,
    invokeMetadataDefaults,
  ]);

  const dirty = useMemo(() => {
    const initial = initialSnapshotRef.current;
    if (!initial) return false;
    const current = buildSnapshot({
      name,
      cardUrl,
      authType,
      bearerToken,
      apiKeyHeader,
      apiKeyValue,
      basicUsername,
      basicPassword,
      extraHeaders,
      invokeMetadataDefaults,
    });
    return JSON.stringify(current) !== JSON.stringify(initial);
  }, [
    name,
    cardUrl,
    authType,
    bearerToken,
    apiKeyHeader,
    apiKeyValue,
    basicUsername,
    basicPassword,
    extraHeaders,
    invokeMetadataDefaults,
  ]);

  const { allowNextNavigation } = usePreventRemoveWhenDirty({ dirty });

  const handleCancel = useCallback(() => {
    blurActiveElement();
    goBackOrHome();
  }, [goBackOrHome]);

  const handleTest = useCallback(async () => {
    if (!agentId || !agent) return;
    blurActiveElement();
    try {
      await validateAgentMutation.mutateAsync(agentId);
      toast.success("Connection OK", `${agent.name} is online.`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Connection failed.";
      toast.error("Test failed", message);
    }
  }, [agent, agentId, validateAgentMutation]);

  const handleAddHeader = () => {
    setExtraHeaders((prev) => appendKeyValueRow(prev));
  };

  const handleHeaderChange = (
    id: string,
    key: "key" | "value",
    value: string,
  ) => {
    setExtraHeaders((prev) => updateKeyValueRows(prev, id, key, value));
  };

  const handleHeaderRemove = (id: string) => {
    setExtraHeaders((prev) => removeKeyValueRow(prev, id));
  };

  const handleAddInvokeMetadataDefault = () => {
    setInvokeMetadataDefaults((prev) => appendKeyValueRow(prev));
  };

  const handleInvokeMetadataDefaultChange = (
    id: string,
    key: "key" | "value",
    value: string,
  ) => {
    setInvokeMetadataDefaults((prev) =>
      updateKeyValueRows(prev, id, key, value),
    );
  };

  const handleInvokeMetadataDefaultRemove = (id: string) => {
    setInvokeMetadataDefaults((prev) => removeKeyValueRow(prev, id));
  };

  const handleAuthTypeChange = (nextType: AgentAuthType) => {
    if (nextType === authType) {
      return;
    }
    setAuthType(nextType);
    setBearerToken("");
    setApiKeyHeader(DEFAULT_API_KEY_HEADER);
    setApiKeyValue("");
    setBasicUsername("");
    setBasicPassword("");
  };

  const validate = () => {
    const nextErrors: { name?: string; cardUrl?: string } = {};
    if (!name.trim()) {
      nextErrors.name = "Agent name is required.";
    }
    if (!cardUrl.trim() || !isValidHttpUrl(cardUrl.trim())) {
      nextErrors.cardUrl = "Valid card URL is required.";
    }
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleSave = async () => {
    if (!validate()) {
      return;
    }
    blurActiveElement();
    setSaveStatus("saving");
    const payload = {
      name: name.trim(),
      cardUrl: cardUrl.trim(),
      authType,
      bearerToken: bearerToken.trim(),
      apiKeyHeader: apiKeyHeader.trim(),
      apiKeyValue: apiKeyValue.trim(),
      basicUsername: basicUsername.trim(),
      basicPassword: basicPassword.trim(),
      extraHeaders,
      invokeMetadataDefaults,
    };
    const isEditing = Boolean(agentId && agent);
    try {
      const result = await executeWithAdminAutoAllowlist({
        isAdmin,
        cardUrl: payload.cardUrl,
        run: () =>
          isEditing
            ? updateAgentMutation.mutateAsync({ id: agentId!, payload })
            : createAgentMutation.mutateAsync(payload),
        confirmAddHost: (host) =>
          confirmAction({
            title: "Host not allowlisted",
            message: `The card URL host "${host}" is not in the proxy allowlist. Add it automatically and continue ${
              isEditing ? "saving" : "creating"
            } the agent?`,
            confirmLabel: "Add and Continue",
            cancelLabel: isEditing ? "Keep Editing" : "Exit Create",
          }),
        addHostToAllowlist: async (host) => {
          await createProxyAllowlistEntry({ host_pattern: host });
        },
        onCancel: async () => {
          if (isEditing) {
            return;
          }
          allowNextNavigation();
          goBackOrHome();
        },
      });

      if (result.status === "cancelled") {
        setSaveStatus("idle");
        return;
      }
      initialSnapshotRef.current = buildSnapshot({
        name: payload.name,
        cardUrl: payload.cardUrl,
        authType: payload.authType,
        bearerToken: payload.bearerToken,
        apiKeyHeader: payload.apiKeyHeader,
        apiKeyValue: payload.apiKeyValue,
        basicUsername: payload.basicUsername,
        basicPassword: payload.basicPassword,
        extraHeaders: payload.extraHeaders,
        invokeMetadataDefaults: payload.invokeMetadataDefaults,
      });
      setSaveStatus("success");
      toast.success("Success", "Agent saved successfully.");
      allowNextNavigation();
      goBackOrHome();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Save failed.";
      setSaveStatus("error");
      toast.error("Save failed", message);
    }
  };

  const handleDelete = async () => {
    if (!agentId || !agent) {
      return;
    }

    blurActiveElement();
    const confirmed = await confirmAction({
      title: "Delete agent",
      message: `Are you sure you want to delete ${agent.name}? This cannot be undone.`,
      confirmLabel: "Delete",
      isDestructive: true,
    });
    if (!confirmed) return;

    setIsDeleting(true);
    try {
      await deleteAgentMutation.mutateAsync(agentId);
      toast.success("Agent deleted", `${agent.name} has been removed.`);
      goBackOrHome();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Delete failed.";
      toast.error("Delete failed", message);
    } finally {
      setIsDeleting(false);
    }
  };

  const refreshSharedCredentialState = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.agents.sharedListRoot(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.agents.catalog(),
      }),
      sharedCredentialQuery.refetch(),
    ]);
  }, [queryClient, sharedCredentialQuery]);

  const handleSaveSharedCredential = useCallback(async () => {
    if (!agentId || !sharedCredentialQuery.data) {
      return;
    }
    const authType = sharedCredentialQuery.data.auth_type;
    if (authType === "bearer" && !sharedToken.trim()) {
      toast.error("Validation failed", "Bearer token is required.");
      return;
    }
    if (authType === "basic") {
      if (!sharedBasicUsername.trim()) {
        toast.error("Validation failed", "Username is required.");
        return;
      }
      if (!sharedBasicPassword.trim()) {
        toast.error("Validation failed", "Password is required.");
        return;
      }
    }

    blurActiveElement();
    setSavingSharedCredential(true);
    try {
      await upsertHubAgentCredential(agentId, {
        token: authType === "bearer" ? sharedToken.trim() : undefined,
        basic_username:
          authType === "basic" ? sharedBasicUsername.trim() : undefined,
        basic_password:
          authType === "basic" ? sharedBasicPassword.trim() : undefined,
      });
      setSharedToken("");
      setSharedBasicPassword("");
      toast.success("Credential saved", "Shared agent credential updated.");
      await refreshSharedCredentialState();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Save failed.";
      toast.error("Save failed", message);
    } finally {
      setSavingSharedCredential(false);
    }
  }, [
    agentId,
    refreshSharedCredentialState,
    sharedBasicPassword,
    sharedBasicUsername,
    sharedCredentialQuery.data,
    sharedToken,
  ]);

  const handleDeleteSharedCredential = useCallback(async () => {
    if (!agentId) {
      return;
    }
    blurActiveElement();
    const confirmed = await confirmAction({
      title: "Delete credential",
      message:
        "Remove your saved credential for this shared agent? You will need to configure it again before chat.",
      confirmLabel: "Delete",
      isDestructive: true,
    });
    if (!confirmed) {
      return;
    }
    setDeletingSharedCredential(true);
    try {
      await deleteHubAgentCredential(agentId);
      setSharedToken("");
      setSharedBasicUsername("");
      setSharedBasicPassword("");
      toast.success(
        "Credential deleted",
        "Your shared agent credential was removed.",
      );
      await refreshSharedCredentialState();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Delete failed.";
      toast.error("Delete failed", message);
    } finally {
      setDeletingSharedCredential(false);
    }
  }, [agentId, refreshSharedCredentialState]);

  if (isSharedAgent) {
    const sharedStatus = sharedCredentialQuery.data;
    const credentialMode = sharedStatus?.credential_mode ?? "none";
    const authType = sharedStatus?.auth_type ?? "none";
    return (
      <ScreenContainer>
        <PageHeader
          title="Agent"
          subtitle="This shared agent is admin-managed. You can only manage your own credential when required."
          rightElement={<BackButton variant="outline" onPress={handleCancel} />}
        />
        <View className="mt-8 rounded-2xl bg-surface p-6 shadow-sm">
          <Text className="text-base font-bold text-white">
            Read-only agent
          </Text>
          <Text className="mt-2 text-[11px] font-medium text-slate-400">
            Please contact your administrator if you need changes to this agent.
          </Text>
          <View className="mt-5 gap-2">
            <Text className="text-xs text-slate-300">Name: {agent?.name}</Text>
            <Text className="text-xs text-slate-400">
              URL: {agent?.cardUrl}
            </Text>
            <Text className="text-xs text-slate-400">
              Auth: {sharedStatus?.auth_type ?? "Loading..."}
            </Text>
            <Text className="text-xs text-slate-400">
              Credential mode: {credentialMode}
            </Text>
          </View>
          <View className="mt-6">
            <Button
              label="Test connection"
              size="sm"
              variant="secondary"
              iconLeft="pulse-outline"
              loading={validateAgentMutation.isPending}
              onPress={handleTest}
            />
          </View>
        </View>

        <View className="mt-6 rounded-2xl bg-surface p-6 shadow-sm">
          <Text className="text-base font-bold text-white">Credential</Text>
          {sharedCredentialQuery.isLoading && !sharedStatus ? (
            <Text className="mt-2 text-[11px] font-medium text-slate-400">
              Loading credential status...
            </Text>
          ) : credentialMode === "user" ? (
            <>
              <Text className="mt-2 text-[11px] font-medium text-slate-400">
                {sharedStatus?.configured
                  ? authType === "basic"
                    ? `Your ${authType} credential is configured (${sharedStatus.username_hint ?? "saved"}).`
                    : `Your ${authType} credential is configured${sharedStatus?.token_last4 ? ` (****${sharedStatus.token_last4})` : ""}.`
                  : `This shared agent requires your ${authType} credential before chat.`}
              </Text>
              <View className="mt-4 gap-3">
                {authType === "bearer" ? (
                  <Input
                    label="Token"
                    placeholder="Enter your bearer token"
                    secureTextEntry
                    value={sharedToken}
                    onChangeText={setSharedToken}
                  />
                ) : null}
                {authType === "basic" ? (
                  <View className="gap-3">
                    <Input
                      label="Username"
                      placeholder="Enter username"
                      value={sharedBasicUsername}
                      onChangeText={setSharedBasicUsername}
                    />
                    <Input
                      label="Password"
                      placeholder="Enter password"
                      secureTextEntry
                      value={sharedBasicPassword}
                      onChangeText={setSharedBasicPassword}
                    />
                  </View>
                ) : null}
                <View className="flex-row gap-3">
                  <Button
                    label={
                      savingSharedCredential ? "Saving..." : "Save credential"
                    }
                    loading={savingSharedCredential}
                    onPress={() => {
                      handleSaveSharedCredential().catch(() => undefined);
                    }}
                  />
                  {sharedStatus?.configured ? (
                    <Button
                      label={
                        deletingSharedCredential
                          ? "Deleting..."
                          : "Delete credential"
                      }
                      variant="danger"
                      loading={deletingSharedCredential}
                      onPress={() => {
                        handleDeleteSharedCredential().catch(() => undefined);
                      }}
                    />
                  ) : null}
                </View>
              </View>
            </>
          ) : credentialMode === "shared" ? (
            <Text className="mt-2 text-[11px] font-medium text-slate-400">
              This shared agent uses an admin-managed credential. No personal
              credential is needed.
            </Text>
          ) : (
            <Text className="mt-2 text-[11px] font-medium text-slate-400">
              This shared agent does not require credentials.
            </Text>
          )}
        </View>
      </ScreenContainer>
    );
  }

  if (isBuiltInAgent) {
    return (
      <ScreenContainer>
        <PageHeader
          title="Agent"
          subtitle="This built-in agent is provided by the local runtime and cannot be edited here."
          rightElement={<BackButton variant="outline" onPress={handleCancel} />}
        />
        <View className="mt-8 rounded-2xl bg-surface p-6 shadow-sm">
          <Text className="text-base font-bold text-white">Built-in agent</Text>
          <Text className="mt-2 text-[11px] font-medium text-slate-400">
            This entry is read-only. Its behavior is managed by the local
            self-management runtime.
          </Text>
          <View className="mt-5 gap-2">
            <Text className="text-xs text-slate-300">Name: {agent?.name}</Text>
            <Text className="text-xs text-slate-400">
              URL: {agent?.cardUrl}
            </Text>
            {agent?.runtime ? (
              <Text className="text-xs text-slate-400">
                Runtime: {agent.runtime}
              </Text>
            ) : null}
          </View>
        </View>
      </ScreenContainer>
    );
  }

  return (
    <ScreenScrollView>
      <PageHeader
        title={agentId ? "Edit Agent" : "New Agent"}
        subtitle="Provide agent card details and credentials."
        rightElement={
          <IconButton
            accessibilityLabel="Go back"
            icon="chevron-back"
            variant="outline"
            size="sm"
            onPress={handleCancel}
          />
        }
      />

      <View className="mt-3 gap-4">
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

        <View className="gap-3">
          <Text className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
            Auth Type
          </Text>
          <View className="flex-row flex-wrap gap-2">
            {authTypes.map((option) => (
              <Pressable
                key={option.value}
                className={`rounded-xl border px-4 py-2 ${
                  authType === option.value
                    ? "border-primary/40 bg-primary/10"
                    : "border-white/5 bg-black/20"
                }`}
                onPress={() => handleAuthTypeChange(option.value)}
              >
                <Text
                  className={`text-[11px] font-bold ${
                    authType === option.value
                      ? "text-primary"
                      : "text-slate-400"
                  }`}
                >
                  {option.label}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>

        {authType === "bearer" ? (
          <Input
            label="Token"
            placeholder="Enter your bearer token"
            secureTextEntry
            value={bearerToken}
            onChangeText={setBearerToken}
          />
        ) : null}

        {authType === "api_key" ? (
          <View className="gap-3">
            <Input
              label="Header Name"
              placeholder={`e.g., ${DEFAULT_API_KEY_HEADER}`}
              value={apiKeyHeader}
              onChangeText={setApiKeyHeader}
            />
            <Input
              label="API Key"
              placeholder="Enter your API key"
              secureTextEntry
              value={apiKeyValue}
              onChangeText={setApiKeyValue}
            />
          </View>
        ) : null}

        {authType === "basic" ? (
          <View className="gap-3">
            <Input
              label="Username"
              placeholder="Enter username"
              value={basicUsername}
              onChangeText={setBasicUsername}
            />
            <Input
              label="Password"
              placeholder="Enter password"
              secureTextEntry
              value={basicPassword}
              onChangeText={setBasicPassword}
            />
          </View>
        ) : null}
      </View>

      <View className="mt-8">
        <Text className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
          Custom Headers
        </Text>
        <View className="mt-3 gap-3">
          {extraHeaders.map((header) => (
            <KeyValueInputRow
              key={header.id}
              keyValue={header.key}
              valueValue={header.value}
              onChangeKey={(value) =>
                handleHeaderChange(header.id, "key", value)
              }
              onChangeValue={(value) =>
                handleHeaderChange(header.id, "value", value)
              }
              onRemove={() => handleHeaderRemove(header.id)}
            />
          ))}
          <Button
            className="self-start"
            label="Add header"
            variant="outline"
            size="sm"
            onPress={handleAddHeader}
          />
        </View>
      </View>

      <View className="mt-8">
        <Text className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
          Invoke Metadata Defaults
        </Text>
        <Text className="mt-2 text-xs text-slate-400">
          Optional agent-level defaults used when request metadata and session
          bindings do not provide a value.
        </Text>
        <View className="mt-3 gap-3">
          {invokeMetadataDefaults.map((item) => (
            <KeyValueInputRow
              key={item.id}
              keyValue={item.key}
              valueValue={item.value}
              onChangeKey={(value) =>
                handleInvokeMetadataDefaultChange(item.id, "key", value)
              }
              onChangeValue={(value) =>
                handleInvokeMetadataDefaultChange(item.id, "value", value)
              }
              onRemove={() => handleInvokeMetadataDefaultRemove(item.id)}
            />
          ))}
          <Button
            className="self-start"
            label="Add default"
            variant="outline"
            size="sm"
            onPress={handleAddInvokeMetadataDefault}
          />
        </View>
      </View>

      <View className="mt-10 flex-row items-center justify-between gap-3">
        <View className="flex-row gap-2">
          <BackButton variant="outline" onPress={handleCancel} />
          {agentId && (
            <Button
              label="Test"
              variant="secondary"
              iconLeft="pulse-outline"
              loading={validateAgentMutation.isPending}
              onPress={handleTest}
            />
          )}
        </View>
        <Button
          label={saveStatus === "saving" ? "Saving..." : "Save"}
          onPress={handleSave}
          loading={saveStatus === "saving"}
        />
      </View>

      {agentId && agent ? (
        <View className="mt-10 rounded-2xl bg-red-500/10 p-5 shadow-sm">
          <Text className="text-sm font-bold text-red-200">Danger zone</Text>
          <Text className="mt-1 text-[11px] font-medium text-red-200/60">
            Deleting an agent removes its local configuration. This action
            cannot be undone.
          </Text>
          <Button
            className="mt-4 self-start"
            label={isDeleting ? "Deleting..." : "Delete agent"}
            variant="danger"
            size="sm"
            onPress={handleDelete}
            loading={isDeleting}
          />
        </View>
      ) : null}

      <View className="h-12" />
    </ScreenScrollView>
  );
}
