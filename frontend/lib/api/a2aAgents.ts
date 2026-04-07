import { apiRequest } from "@/lib/api/client";
import {
  parsePaginatedListResponse,
  resolveNextPageWithFallback,
} from "@/lib/api/pagination";

type A2AAuthType = "none" | "bearer" | "basic";
export type A2AAgentHealthStatus =
  | "unknown"
  | "healthy"
  | "degraded"
  | "unavailable";
export type A2AAgentHealthBucket = "all" | A2AAgentHealthStatus | "attention";

export type A2AAgentCardValidationResponse = {
  success: boolean;
  message: string;
  card_name?: string | null;
  card_description?: string | null;
  card?: Record<string, unknown> | null;
  validation_errors?: string[] | null;
  validation_warnings?: string[] | null;
};

export type A2AAgentResponse = {
  id: string;
  name: string;
  card_url: string;
  auth_type: A2AAuthType;
  auth_header?: string | null;
  auth_scheme?: string | null;
  enabled: boolean;
  health_status: A2AAgentHealthStatus;
  consecutive_health_check_failures: number;
  last_health_check_at?: string | null;
  last_successful_health_check_at?: string | null;
  last_health_check_error?: string | null;
  tags: string[];
  extra_headers: Record<string, string>;
  invoke_metadata_defaults: Record<string, string>;
  token_last4?: string | null;
  username_hint?: string | null;
  created_at: string;
  updated_at: string;
};

export type A2AAgentListResponse = {
  items: A2AAgentResponse[];
  pagination: {
    page: number;
    size: number;
    total: number;
    pages: number;
  };
  meta: {
    counts: {
      healthy: number;
      degraded: number;
      unavailable: number;
      unknown: number;
    };
  };
};

type A2AAgentHealthCheckResponse = {
  summary: {
    requested: number;
    checked: number;
    skipped_cooldown: number;
    healthy: number;
    degraded: number;
    unavailable: number;
    unknown: number;
  };
  items: {
    agent_id: string;
    health_status: A2AAgentHealthStatus;
    checked_at: string;
    skipped_cooldown: boolean;
    error?: string | null;
  }[];
};

export type A2AAgentCreateRequest = {
  name: string;
  card_url: string;
  auth_type: A2AAuthType;
  auth_header?: string;
  auth_scheme?: string;
  token?: string;
  basic_username?: string;
  basic_password?: string;
  enabled: boolean;
  tags: string[];
  extra_headers: Record<string, string>;
  invoke_metadata_defaults: Record<string, string>;
};

type A2AAgentUpdateRequest = Partial<A2AAgentCreateRequest>;

export type A2AAgentInvokeRequest = {
  query: string;
  conversationId?: string;
  userMessageId?: string;
  agentMessageId?: string;
  resumeFromSequence?: number;
  metadata?: Record<string, unknown>;
  sessionBinding?: {
    provider?: string | null;
    externalSessionId?: string | null;
  };
};

type A2AAgentInvokeResponse = {
  success: boolean;
  content?: string | null;
  error?: string | null;
  error_code?: string | null;
  source?: string | null;
  jsonrpc_code?: number | null;
  missing_params?: { name: string; required: boolean }[] | null;
  upstream_error?: Record<string, unknown> | null;
  agent_name?: string | null;
  agent_url?: string | null;
};

type WsTicketResponse = {
  token: string;
  expires_at: string;
  expires_in: number;
};

export const listAgents = (
  page = 1,
  size = 50,
  healthBucket: A2AAgentHealthBucket = "all",
) =>
  apiRequest<A2AAgentListResponse>("/me/a2a/agents", {
    query: { page, size, health_bucket: healthBucket },
  });

export const listAgentsPage = async (input?: {
  page?: number;
  size?: number;
  healthBucket?: A2AAgentHealthBucket;
}) => {
  const page =
    typeof input?.page === "number" && Number.isFinite(input.page)
      ? Math.max(1, Math.floor(input.page))
      : 1;
  const size =
    typeof input?.size === "number" && Number.isFinite(input.size)
      ? Math.max(1, Math.floor(input.size))
      : 50;
  const healthBucket = input?.healthBucket ?? "all";

  const response = await listAgents(page, size, healthBucket);
  const parsed = parsePaginatedListResponse(response);

  return {
    items: parsed.items,
    pagination: response.pagination,
    meta: response.meta,
    nextPage: resolveNextPageWithFallback({ parsed, page, size }),
  };
};

export const createAgent = (payload: A2AAgentCreateRequest) =>
  apiRequest<A2AAgentResponse, A2AAgentCreateRequest>("/me/a2a/agents", {
    method: "POST",
    body: payload,
  });

export const updateAgent = (agentId: string, payload: A2AAgentUpdateRequest) =>
  apiRequest<A2AAgentResponse, A2AAgentUpdateRequest>(
    `/me/a2a/agents/${agentId}`,
    {
      method: "PUT",
      body: payload,
    },
  );

export const deleteAgent = (agentId: string) =>
  apiRequest<void>(`/me/a2a/agents/${agentId}`, { method: "DELETE" });

export const validateAgentCard = (agentId: string) =>
  apiRequest<A2AAgentCardValidationResponse>(
    `/me/a2a/agents/${agentId}/card:validate`,
    {
      method: "POST",
    },
  );

export const checkAgentsHealth = (force = false) =>
  apiRequest<A2AAgentHealthCheckResponse>("/me/a2a/agents/check-health", {
    method: "POST",
    query: { force: force ? "true" : "false" },
  });

export const checkAgentHealth = (agentId: string, force = true) =>
  apiRequest<A2AAgentHealthCheckResponse>(
    `/me/a2a/agents/${agentId}/check-health`,
    {
      method: "POST",
      query: { force: force ? "true" : "false" },
    },
  );

export const getInvokeWsTicket = (agentId: string) =>
  apiRequest<WsTicketResponse>(`/me/a2a/agents/${agentId}/invoke/ws-token`, {
    method: "POST",
  });

export const invokeAgent = (agentId: string, payload: A2AAgentInvokeRequest) =>
  apiRequest<A2AAgentInvokeResponse, A2AAgentInvokeRequest>(
    `/me/a2a/agents/${agentId}/invoke`,
    {
      method: "POST",
      body: payload,
    },
  );
