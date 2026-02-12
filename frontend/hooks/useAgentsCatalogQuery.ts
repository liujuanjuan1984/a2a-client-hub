import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { headersToEntries } from "@/lib/agentHeaders";
import { buildAgentUpsertPayload } from "@/lib/agentUpsert";
import {
  createAgent,
  deleteAgent,
  listAgents,
  updateAgent,
  validateAgentCard,
  type A2AAgentCardValidationResponse,
  type A2AAgentResponse,
} from "@/lib/api/a2aAgents";
import {
  listHubAgents,
  validateHubAgentCard,
  type HubA2AAgentUserResponse,
} from "@/lib/api/hubA2aAgentsUser";
import { queryKeys } from "@/lib/queryKeys";
import { type AgentConfig, useAgentStore } from "@/store/agents";

export type CreateAgentPayload = Omit<
  AgentConfig,
  "id" | "source" | "status" | "lastCheckedAt" | "lastError"
>;

export type UpdateAgentPayload = Partial<
  Omit<AgentConfig, "id" | "source" | "status" | "lastCheckedAt" | "lastError">
>;

const toAgentConfig = (agent: A2AAgentResponse): AgentConfig => ({
  id: agent.id,
  source: "personal",
  name: agent.name,
  cardUrl: agent.card_url,
  authType: agent.auth_type === "bearer" ? "bearer" : "none",
  bearerToken: "",
  apiKeyHeader: "X-API-Key",
  apiKeyValue: "",
  basicUsername: "",
  basicPassword: "",
  extraHeaders: headersToEntries(agent.extra_headers ?? {}),
  status: "idle",
});

const toSharedAgentConfig = (agent: HubA2AAgentUserResponse): AgentConfig => ({
  id: agent.id,
  source: "shared",
  name: agent.name,
  cardUrl: agent.card_url,
  authType: "none",
  bearerToken: "",
  apiKeyHeader: "X-API-Key",
  apiKeyValue: "",
  basicUsername: "",
  basicPassword: "",
  extraHeaders: [],
  status: "idle",
});

const mergeTransientStatus = (
  nextAgents: AgentConfig[],
  previousAgents: AgentConfig[],
) => {
  const previousById = new Map(
    previousAgents.map((agent) => [agent.id, agent]),
  );
  return nextAgents.map((agent) => {
    const previous = previousById.get(agent.id);
    if (!previous) {
      return agent;
    }
    return {
      ...agent,
      status: previous.status,
      lastCheckedAt: previous.lastCheckedAt,
      lastError: previous.lastError,
    };
  });
};

const getCatalogCache = (catalog: AgentConfig[] | undefined) => catalog ?? [];

const patchAgentInCatalog = (
  catalog: AgentConfig[] | undefined,
  agentId: string,
  updater: (agent: AgentConfig) => AgentConfig,
) => {
  if (!catalog) {
    return catalog;
  }
  return catalog.map((agent) =>
    agent.id === agentId ? updater(agent) : agent,
  );
};

const toValidationError = (response: A2AAgentCardValidationResponse) => {
  const rawMessage = response.validation_errors?.[0] || response.message;
  if (typeof rawMessage === "string" && rawMessage.trim()) {
    return rawMessage;
  }
  if (rawMessage) {
    return JSON.stringify(rawMessage);
  }
  return "Connection failed";
};

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
  });

export function useAgentsCatalogQuery(enabled = true) {
  const queryClient = useQueryClient();

  return useQuery({
    queryKey: queryKeys.agents.catalog(),
    enabled,
    queryFn: async () => {
      const previousAgents = getCatalogCache(
        queryClient.getQueryData<AgentConfig[]>(queryKeys.agents.catalog()),
      );

      const [personalResult, sharedResult] = await Promise.allSettled([
        listAgents(1, 200),
        listHubAgents(1, 200),
      ]);

      if (
        personalResult.status === "rejected" &&
        sharedResult.status === "rejected"
      ) {
        throw personalResult.reason ?? sharedResult.reason;
      }

      const personalAgents =
        personalResult.status === "fulfilled"
          ? personalResult.value.items.map(toAgentConfig)
          : previousAgents.filter((agent) => agent.source === "personal");

      const sharedAgents =
        sharedResult.status === "fulfilled"
          ? sharedResult.value.items.map(toSharedAgentConfig)
          : previousAgents.filter((agent) => agent.source === "shared");

      const mergedAgents = mergeTransientStatus(
        [...personalAgents, ...sharedAgents],
        previousAgents,
      );

      const activeAgentId = useAgentStore.getState().activeAgentId;
      if (
        activeAgentId &&
        !mergedAgents.some((agent) => agent.id === activeAgentId)
      ) {
        useAgentStore.getState().setActiveAgent(null);
      }

      return mergedAgents;
    },
  });
}

export function useCreateAgentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateAgentPayload) => {
      return await createAgent(toUpsertPayload(payload));
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.agents.catalog(),
      });
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
        throw new Error("Agent not found.");
      }
      if (existing.source !== "personal") {
        throw new Error(
          "This agent is managed by an admin and cannot be edited.",
        );
      }

      const next = { ...existing, ...payload };
      return await updateAgent(id, toUpsertPayload(next));
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.agents.catalog(),
      });
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
      if (existing && existing.source !== "personal") {
        throw new Error(
          "This agent is managed by an admin and cannot be removed.",
        );
      }
      await deleteAgent(id);
      return id;
    },
    onSuccess: async (id) => {
      queryClient.setQueryData<AgentConfig[] | undefined>(
        queryKeys.agents.catalog(),
        (catalog) => catalog?.filter((agent) => agent.id !== id),
      );

      if (useAgentStore.getState().activeAgentId === id) {
        useAgentStore.getState().setActiveAgent(null);
      }
      await queryClient.invalidateQueries({
        queryKey: queryKeys.agents.catalog(),
      });
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
        throw new Error("Agent not found.");
      }

      const response =
        agent.source === "shared"
          ? await validateHubAgentCard(agentId)
          : await validateAgentCard(agentId);

      if (!response.success) {
        throw new Error(toValidationError(response));
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
      const message =
        error instanceof Error ? error.message : "Connection failed";
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
