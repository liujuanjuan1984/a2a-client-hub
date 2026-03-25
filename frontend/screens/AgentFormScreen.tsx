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
import { createProxyAllowlistEntry } from "@/lib/api/adminProxyAllowlist";
import { confirmAction } from "@/lib/confirm";
import { blurActiveElement } from "@/lib/focus";
import { generateId } from "@/lib/id";
import { backOrHome } from "@/lib/navigation";
import { toast } from "@/lib/toast";
import { type AgentHeader } from "@/store/agents";
import { useSessionStore } from "@/store/session";

const authTypes: { label: string; value: AgentAuthType }[] = [
  { label: "No Auth", value: "none" },
  { label: "Bearer", value: "bearer" },
  { label: "API Key", value: "api_key" },
  { label: "Basic", value: "basic" },
];

const createHeader = (): AgentHeader => ({
  id: generateId(),
  key: "",
  value: "",
});

const validateUrl = (value: string) => {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
};

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
}): Snapshot => ({
  name: value.name.trim(),
  cardUrl: value.cardUrl.trim(),
  authType: value.authType,
  bearerToken: value.bearerToken.trim(),
  apiKeyHeader: value.apiKeyHeader.trim(),
  apiKeyValue: value.apiKeyValue.trim(),
  basicUsername: value.basicUsername.trim(),
  basicPassword: value.basicPassword.trim(),
  extraHeaders: value.extraHeaders
    .map((item) => ({ key: item.key.trim(), value: item.value.trim() }))
    .filter((item) => item.key || item.value),
});

export function AgentFormScreen({ agentId }: AgentFormScreenProps) {
  const router = useRouter();
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
    agent?.apiKeyHeader ?? "X-API-Key",
  );
  const [apiKeyValue, setApiKeyValue] = useState(agent?.apiKeyValue ?? "");
  const [basicUsername, setBasicUsername] = useState(
    agent?.basicUsername ?? "",
  );
  const [basicPassword, setBasicPassword] = useState(
    agent?.basicPassword ?? "",
  );
  const [extraHeaders, setExtraHeaders] = useState<AgentHeader[]>(
    agent?.extraHeaders.length ? agent.extraHeaders : [createHeader()],
  );
  const [errors, setErrors] = useState<{ name?: string; cardUrl?: string }>({});
  const [saveStatus, setSaveStatus] = useState<
    "idle" | "saving" | "success" | "error"
  >("idle");
  const [isDeleting, setIsDeleting] = useState(false);
  const initializedFromAgentRef = useRef(false);
  const initialSnapshotRef = useRef<Snapshot | null>(null);

  const goBackOrHome = useCallback(() => backOrHome(router), [router]);
  const isSharedAgent = Boolean(agentId && agent && agent.source === "shared");

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
    setApiKeyHeader(agent.apiKeyHeader ?? "X-API-Key");
    setApiKeyValue(agent.apiKeyValue ?? "");
    setBasicUsername(agent.basicUsername ?? "");
    setBasicPassword(agent.basicPassword ?? "");
    setExtraHeaders(
      agent.extraHeaders.length ? agent.extraHeaders : [createHeader()],
    );

    initialSnapshotRef.current = buildSnapshot({
      name: agent.name ?? "",
      cardUrl: agent.cardUrl ?? "",
      authType: agent.authType ?? "none",
      bearerToken: agent.bearerToken ?? "",
      apiKeyHeader: agent.apiKeyHeader ?? "X-API-Key",
      apiKeyValue: agent.apiKeyValue ?? "",
      basicUsername: agent.basicUsername ?? "",
      basicPassword: agent.basicPassword ?? "",
      extraHeaders: agent.extraHeaders.length ? agent.extraHeaders : [],
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
    setExtraHeaders((prev) => [...prev, createHeader()]);
  };

  const handleHeaderChange = (
    id: string,
    key: "key" | "value",
    value: string,
  ) => {
    setExtraHeaders((prev) =>
      prev.map((item) => (item.id === id ? { ...item, [key]: value } : item)),
    );
  };

  const handleHeaderRemove = (id: string) => {
    setExtraHeaders((prev) => prev.filter((item) => item.id !== id));
  };

  const handleAuthTypeChange = (nextType: AgentAuthType) => {
    if (nextType === authType) {
      return;
    }
    setAuthType(nextType);
    setBearerToken("");
    setApiKeyHeader("X-API-Key");
    setApiKeyValue("");
    setBasicUsername("");
    setBasicPassword("");
  };

  const validate = () => {
    const nextErrors: { name?: string; cardUrl?: string } = {};
    if (!name.trim()) {
      nextErrors.name = "Agent name is required.";
    }
    if (!cardUrl.trim() || !validateUrl(cardUrl.trim())) {
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

  if (isSharedAgent) {
    return (
      <ScreenContainer>
        <PageHeader
          title="Agent"
          subtitle="This agent is provided by an admin and cannot be edited here."
          rightElement={<BackButton variant="outline" onPress={handleCancel} />}
        />
        <View className="mt-8 rounded-2xl bg-surface p-6 shadow-sm">
          <Text className="text-base font-bold text-white">
            Read-only agent
          </Text>
          <Text className="mt-2 text-[11px] font-medium text-slate-400">
            Please contact your administrator if you need changes to this agent.
          </Text>
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
              placeholder="e.g., X-API-Key"
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
