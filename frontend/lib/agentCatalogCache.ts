import { type AgentConfig } from "@/store/agents";

export const AGENT_ERROR_MESSAGES = {
  notFound: "Agent no longer exists. Please refresh the list.",
  readOnlyEdit: "This agent is managed by an admin and cannot be edited.",
  readOnlyDelete: "This agent is managed by an admin and cannot be removed.",
  connectionFailed: "Connection failed",
} as const;

type ValidationResponseLike = {
  validation_errors?: unknown[] | null;
  message?: unknown;
};

const canReuseAgentValidationState = (
  previous: AgentConfig,
  next: AgentConfig,
): boolean =>
  previous.source === next.source && previous.cardUrl === next.cardUrl;

export const mergeTransientAgentState = (
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
    if (!canReuseAgentValidationState(previous, agent)) {
      return agent;
    }
    return {
      ...agent,
      status: previous.status,
      lastCheckedAt: previous.lastCheckedAt,
      lastError: previous.lastError,
      capabilities: previous.capabilities ?? agent.capabilities,
    };
  });
};

export const patchAgentInCatalog = (
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

export const upsertAgentInCatalog = (
  catalog: AgentConfig[] | undefined,
  nextAgent: AgentConfig,
  preserveStatusFromAgentId?: string,
) => {
  const current = catalog ?? [];
  const preserveFrom = current.find(
    (item) => item.id === (preserveStatusFromAgentId ?? nextAgent.id),
  );
  const canReuseValidationState =
    preserveFrom && canReuseAgentValidationState(preserveFrom, nextAgent);

  const merged = {
    ...nextAgent,
    status: canReuseValidationState ? preserveFrom.status : nextAgent.status,
    lastCheckedAt: canReuseValidationState
      ? preserveFrom.lastCheckedAt
      : nextAgent.lastCheckedAt,
    lastError: canReuseValidationState
      ? preserveFrom.lastError
      : nextAgent.lastError,
    capabilities: canReuseValidationState
      ? (preserveFrom.capabilities ?? nextAgent.capabilities)
      : nextAgent.capabilities,
  };

  return [merged, ...current.filter((item) => item.id !== merged.id)];
};

export const removeAgentFromCatalog = (
  catalog: AgentConfig[] | undefined,
  agentId: string,
) => catalog?.filter((agent) => agent.id !== agentId);

export const shouldClearActiveAgent = (
  activeAgentId: string | null,
  catalog: AgentConfig[] | undefined,
) => {
  if (!activeAgentId) {
    return false;
  }
  return !(catalog ?? []).some((agent) => agent.id === activeAgentId);
};

export const toValidationErrorMessage = (
  response: ValidationResponseLike,
  fallback = AGENT_ERROR_MESSAGES.connectionFailed,
) => {
  const rawMessage = response.validation_errors?.[0] || response.message;
  if (typeof rawMessage === "string" && rawMessage.trim()) {
    return rawMessage;
  }
  if (rawMessage) {
    return JSON.stringify(rawMessage);
  }
  return fallback;
};
