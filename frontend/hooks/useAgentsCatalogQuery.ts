import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import {
  AGENT_ERROR_MESSAGES,
  mergeTransientAgentState,
  patchAgentInCatalog,
  removeAgentFromCatalog,
  shouldClearActiveAgent,
  toValidationErrorMessage,
  upsertAgentInCatalog,
} from "@/lib/agentCatalogCache";
import { headersToEntries } from "@/lib/agentHeaders";
import { buildAgentUpsertPayload } from "@/lib/agentUpsert";
import {
  checkAgentHealth,
  createAgent,
  deleteAgent,
  updateAgent,
  validateAgentCard,
  type A2AAgentResponse,
} from "@/lib/api/a2aAgents";
import {
  listAgentsCatalog,
  type UnifiedAgentCatalogItemResponse,
} from "@/lib/api/agentsCatalog";
import { ApiRequestError } from "@/lib/api/client";
import { validateHubAgentCard } from "@/lib/api/hubA2aAgentsUser";
import { queryKeys } from "@/lib/queryKeys";
import { type AgentConfig, useAgentStore } from "@/store/agents";

type CreateAgentPayload = Omit<
  AgentConfig,
  "id" | "source" | "status" | "lastCheckedAt" | "lastError"
>;

type UpdateAgentPayload = Partial<
  Omit<AgentConfig, "id" | "source" | "status" | "lastCheckedAt" | "lastError">
>;

const toAgentConfig = (
  agent: UnifiedAgentCatalogItemResponse,
): AgentConfig => ({
  id: agent.id,
  source: agent.source,
  name: agent.name,
  cardUrl: agent.card_url,
  authType:
    agent.auth_type === "bearer"
      ? "bearer"
      : agent.auth_type === "basic"
        ? "basic"
        : "none",
  bearerToken: "",
  apiKeyHeader: "X-API-Key",
  apiKeyValue: "",
  basicUsername: "",
  basicPassword: "",
  extraHeaders: headersToEntries(agent.extra_headers ?? {}),
  invokeMetadataDefaults: headersToEntries(
    agent.invoke_metadata_defaults ?? {},
  ),
  status: "idle",
  enabled: agent.enabled,
  healthStatus: agent.health_status,
  lastHealthCheckAt: agent.last_health_check_at ?? undefined,
  lastHealthCheckError: agent.last_health_check_error ?? undefined,
  lastHealthCheckReasonCode: agent.last_health_check_reason_code ?? undefined,
  credentialMode: agent.credential_mode ?? undefined,
  credentialConfigured: agent.credential_configured ?? undefined,
  credentialDisplayHint: agent.credential_display_hint ?? undefined,
  description: agent.description ?? undefined,
  runtime: agent.runtime ?? undefined,
  resources: agent.resources ?? undefined,
});

const toPersonalAgentConfig = (agent: A2AAgentResponse): AgentConfig => ({
  id: agent.id,
  source: "personal",
  name: agent.name,
  cardUrl: agent.card_url,
  authType:
    agent.auth_type === "bearer"
      ? "bearer"
      : agent.auth_type === "basic"
        ? "basic"
        : "none",
  bearerToken: "",
  apiKeyHeader: "X-API-Key",
  apiKeyValue: "",
  basicUsername: "",
  basicPassword: "",
  extraHeaders: headersToEntries(agent.extra_headers ?? {}),
  invokeMetadataDefaults: headersToEntries(
    agent.invoke_metadata_defaults ?? {},
  ),
  status: "idle",
  enabled: agent.enabled,
  healthStatus: agent.health_status,
  lastHealthCheckAt: agent.last_health_check_at ?? undefined,
  lastHealthCheckError: agent.last_health_check_error ?? undefined,
  lastHealthCheckReasonCode: agent.last_health_check_reason_code ?? undefined,
});

const getCatalogCache = (catalog: AgentConfig[] | undefined) => catalog ?? [];

const toUpsertPayload = (input: {
  name: string;
  cardUrl: string;
  authType: AgentConfig["authType"];
  bearerToken: string;
  apiKeyHeader: string;
  apiKeyValue: string;
  basicUsername: string;
  basicPassword: string;
  extraHeaders: AgentConfig["extraHeaders"];
  invokeMetadataDefaults: AgentConfig["invokeMetadataDefaults"];
}) =>
  buildAgentUpsertPayload({
    name: input.name,
    cardUrl: input.cardUrl,
    authType: input.authType,
    bearerToken: input.bearerToken,
    apiKeyHeader: input.apiKeyHeader,
    apiKeyValue: input.apiKeyValue,
    basicUsername: input.basicUsername,
    basicPassword: input.basicPassword,
    extraHeaders: input.extraHeaders,
    invokeMetadataDefaults: input.invokeMetadataDefaults,
  });

const refreshActiveCatalogQuery = async (
  queryClient: ReturnType<typeof useQueryClient>,
) => {
  await queryClient.refetchQueries({
    queryKey: queryKeys.agents.catalog(),
    exact: true,
    type: "active",
  });
};

const invalidatePersonalAgentLists = async (
  queryClient: ReturnType<typeof useQueryClient>,
) => {
  await queryClient.invalidateQueries({
    queryKey: queryKeys.agents.listRoot(),
  });
};

const toNotFoundError = () => new Error(AGENT_ERROR_MESSAGES.notFound);

const isNotFoundError = (error: unknown) =>
  error instanceof ApiRequestError && error.status === 404;

export function useAgentsCatalogQuery(enabled = true) {
  const queryClient = useQueryClient();
  const activeAgentId = useAgentStore((state) => state.activeAgentId);
  const setActiveAgent = useAgentStore((state) => state.setActiveAgent);

  const query = useQuery({
    queryKey: queryKeys.agents.catalog(),
    enabled,
    queryFn: async () => {
      const previousAgents = getCatalogCache(
        queryClient.getQueryData<AgentConfig[]>(queryKeys.agents.catalog()),
      );
      const response = await listAgentsCatalog();
      const nextAgents = response.items.map(toAgentConfig);
      return mergeTransientAgentState(nextAgents, previousAgents);
    },
  });

  useEffect(() => {
    if (!shouldClearActiveAgent(activeAgentId, query.data)) {
      return;
    }
    setActiveAgent(null);
  }, [activeAgentId, query.data, setActiveAgent]);

  return query;
}

export function useCreateAgentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateAgentPayload) => {
      return await createAgent(toUpsertPayload(payload));
    },
    onSuccess: async (response) => {
      queryClient.setQueryData<AgentConfig[] | undefined>(
        queryKeys.agents.catalog(),
        (catalog) =>
          upsertAgentInCatalog(catalog, toPersonalAgentConfig(response)),
      );
      try {
        await checkAgentHealth(response.id, true);
      } catch {
        // Keep create success independent from the follow-up availability check.
      }
      await Promise.all([
        refreshActiveCatalogQuery(queryClient),
        invalidatePersonalAgentLists(queryClient),
      ]);
    },
  });
}

export function useUpdateAgentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      id,
      payload,
    }: {
      id: string;
      payload: UpdateAgentPayload;
    }) => {
      const catalog = getCatalogCache(
        queryClient.getQueryData<AgentConfig[]>(queryKeys.agents.catalog()),
      );
      const existing = catalog.find((agent) => agent.id === id);
      if (!existing) {
        throw toNotFoundError();
      }
      if (existing.source !== "personal") {
        throw new Error(AGENT_ERROR_MESSAGES.readOnlyEdit);
      }

      const next = { ...existing, ...payload };
      try {
        return await updateAgent(id, toUpsertPayload(next));
      } catch (error) {
        if (isNotFoundError(error)) {
          throw toNotFoundError();
        }
        throw error;
      }
    },
    onSuccess: async (response, variables) => {
      queryClient.setQueryData<AgentConfig[] | undefined>(
        queryKeys.agents.catalog(),
        (catalog) =>
          upsertAgentInCatalog(
            catalog,
            toPersonalAgentConfig(response),
            variables.id,
          ),
      );
      await refreshActiveCatalogQuery(queryClient);
    },
  });
}

export function useDeleteAgentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      const catalog = getCatalogCache(
        queryClient.getQueryData<AgentConfig[]>(queryKeys.agents.catalog()),
      );
      const existing = catalog.find((agent) => agent.id === id);
      if (!existing) {
        throw toNotFoundError();
      }
      if (existing.source !== "personal") {
        throw new Error(AGENT_ERROR_MESSAGES.readOnlyDelete);
      }

      try {
        await deleteAgent(id);
      } catch (error) {
        if (!isNotFoundError(error)) {
          throw error;
        }
      }
      return id;
    },
    onSuccess: async (id) => {
      queryClient.setQueryData<AgentConfig[] | undefined>(
        queryKeys.agents.catalog(),
        (catalog) => removeAgentFromCatalog(catalog, id),
      );

      const activeAgentId = useAgentStore.getState().activeAgentId;
      const nextCatalog = queryClient.getQueryData<AgentConfig[]>(
        queryKeys.agents.catalog(),
      );
      if (shouldClearActiveAgent(activeAgentId, nextCatalog)) {
        useAgentStore.getState().setActiveAgent(null);
      }

      await refreshActiveCatalogQuery(queryClient);
    },
  });
}

export function useValidateAgentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (agentId: string) => {
      const catalog = getCatalogCache(
        queryClient.getQueryData<AgentConfig[]>(queryKeys.agents.catalog()),
      );
      const agent = catalog.find((item) => item.id === agentId);
      if (!agent) {
        throw toNotFoundError();
      }

      let response;
      try {
        response =
          agent.source === "builtin"
            ? {
                success: true,
                message: "Built-in agent is managed by the local runtime.",
              }
            : agent.source === "shared"
              ? await validateHubAgentCard(agentId)
              : await validateAgentCard(agentId);
      } catch (error) {
        if (isNotFoundError(error)) {
          throw toNotFoundError();
        }
        throw error;
      }

      if (!response.success) {
        throw new Error(toValidationErrorMessage(response));
      }

      return {
        agentId,
        checkedAt: new Date().toISOString(),
      };
    },
    onMutate: (agentId) => {
      queryClient.setQueryData<AgentConfig[] | undefined>(
        queryKeys.agents.catalog(),
        (catalog) =>
          patchAgentInCatalog(catalog, agentId, (agent) => ({
            ...agent,
            status: "checking",
            lastError: undefined,
          })),
      );
    },
    onSuccess: ({ agentId, checkedAt }) => {
      queryClient.setQueryData<AgentConfig[] | undefined>(
        queryKeys.agents.catalog(),
        (catalog) =>
          patchAgentInCatalog(catalog, agentId, (agent) => ({
            ...agent,
            status: "success",
            lastCheckedAt: checkedAt,
            lastError: undefined,
          })),
      );
    },
    onError: (error, agentId) => {
      if (
        error instanceof Error &&
        error.message === AGENT_ERROR_MESSAGES.notFound
      ) {
        queryClient.setQueryData<AgentConfig[] | undefined>(
          queryKeys.agents.catalog(),
          (catalog) => removeAgentFromCatalog(catalog, agentId),
        );
        const activeAgentId = useAgentStore.getState().activeAgentId;
        const nextCatalog = queryClient.getQueryData<AgentConfig[]>(
          queryKeys.agents.catalog(),
        );
        if (shouldClearActiveAgent(activeAgentId, nextCatalog)) {
          useAgentStore.getState().setActiveAgent(null);
        }
        return;
      }

      const message =
        error instanceof Error
          ? error.message
          : AGENT_ERROR_MESSAGES.connectionFailed;
      queryClient.setQueryData<AgentConfig[] | undefined>(
        queryKeys.agents.catalog(),
        (catalog) =>
          patchAgentInCatalog(catalog, agentId, (agent) => ({
            ...agent,
            status: "error",
            lastCheckedAt: new Date().toISOString(),
            lastError: message,
          })),
      );
    },
  });
}
