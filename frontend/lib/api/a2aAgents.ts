import { apiRequest } from "@/lib/api/client";

export type A2AAuthType = "none" | "bearer";

export type A2AAgentCardValidationResponse = {
  success: boolean;
  message: string;
  card_name?: string | null;
  card_description?: string | null;
  card?: Record<string, unknown> | null;
  validation_errors?: string[] | null;
};

export type A2AAgentResponse = {
  id: string;
  name: string;
  card_url: string;
  auth_type: A2AAuthType;
  auth_header?: string | null;
  auth_scheme?: string | null;
  enabled: boolean;
  tags: string[];
  extra_headers: Record<string, string>;
  token_last4?: string | null;
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
  meta: Record<string, unknown>;
};

export type A2AAgentCreateRequest = {
  name: string;
  card_url: string;
  auth_type: A2AAuthType;
  auth_header?: string;
  auth_scheme?: string;
  token?: string;
  enabled: boolean;
  tags: string[];
  extra_headers: Record<string, string>;
};

export type A2AAgentUpdateRequest = Partial<A2AAgentCreateRequest>;

export type A2AAgentInvokeRequest = {
  query: string;
  conversationId?: string;
  contextId?: string;
  userMessageId?: string;
  clientAgentMessageId?: string;
  resumeFromSequence?: number;
  metadata?: Record<string, unknown>;
};

export type A2AAgentInvokeResponse = {
  success: boolean;
  content?: string | null;
  error?: string | null;
  error_code?: string | null;
  agent_name?: string | null;
  agent_url?: string | null;
};

export type WsTicketResponse = {
  token: string;
  expires_at: string;
  expires_in: number;
};

export const listAgents = (page = 1, size = 50) =>
  apiRequest<A2AAgentListResponse>("/me/a2a/agents", {
    query: { page, size },
  });

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
