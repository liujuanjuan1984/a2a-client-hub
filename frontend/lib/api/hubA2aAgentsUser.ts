import { type A2AAgentCardValidationResponse } from "@/lib/api/a2aAgents";
import { apiRequest } from "@/lib/api/client";

export type HubA2AAgentUserResponse = {
  id: string;
  name: string;
  card_url: string;
  auth_type: "none" | "bearer" | "basic";
  credential_mode: "none" | "shared" | "user";
  credential_configured: boolean;
  credential_display_hint?: string | null;
  tags: string[];
};

export type HubA2AAgentUserListResponse = {
  items: HubA2AAgentUserResponse[];
  pagination: {
    page: number;
    size: number;
    total: number;
    pages: number;
  };
  meta: Record<string, unknown>;
};

export type HubA2AAgentInvokeRequest = {
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

export type HubA2AAgentInvokeResponse = {
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

export type HubWsTicketResponse = {
  token: string;
  expires_at: string;
  expires_in: number;
};

export type HubA2AUserCredentialStatusResponse = {
  agent_id: string;
  auth_type: "none" | "bearer" | "basic";
  credential_mode: "none" | "shared" | "user";
  configured: boolean;
  token_last4?: string | null;
  username_hint?: string | null;
};

export type HubA2AUserCredentialUpsertRequest = {
  token?: string | null;
  basic_username?: string | null;
  basic_password?: string | null;
};

export const listHubAgents = (page = 1, size = 200) =>
  apiRequest<HubA2AAgentUserListResponse>("/a2a/agents", {
    query: { page, size },
  });

export const invokeHubAgent = (
  agentId: string,
  payload: HubA2AAgentInvokeRequest,
) =>
  apiRequest<HubA2AAgentInvokeResponse, HubA2AAgentInvokeRequest>(
    `/a2a/agents/${encodeURIComponent(agentId)}/invoke`,
    { method: "POST", body: payload },
  );

// These endpoints are expected to be added as part of hub streaming parity work.
export const getHubInvokeWsTicket = (agentId: string) =>
  apiRequest<HubWsTicketResponse>(
    `/a2a/agents/${encodeURIComponent(agentId)}/invoke/ws-token`,
    { method: "POST" },
  );

export const validateHubAgentCard = (agentId: string) =>
  apiRequest<A2AAgentCardValidationResponse>(
    `/a2a/agents/${encodeURIComponent(agentId)}/card:validate`,
    { method: "POST" },
  );

export const getHubAgentCredentialStatus = (agentId: string) =>
  apiRequest<HubA2AUserCredentialStatusResponse>(
    `/a2a/agents/${encodeURIComponent(agentId)}/credential`,
  );

export const upsertHubAgentCredential = (
  agentId: string,
  payload: HubA2AUserCredentialUpsertRequest,
) =>
  apiRequest<
    HubA2AUserCredentialStatusResponse,
    HubA2AUserCredentialUpsertRequest
  >(`/a2a/agents/${encodeURIComponent(agentId)}/credential`, {
    method: "PUT",
    body: payload,
  });

export const deleteHubAgentCredential = (agentId: string) =>
  apiRequest<void>(`/a2a/agents/${encodeURIComponent(agentId)}/credential`, {
    method: "DELETE",
  });
