import { apiRequest } from "@/lib/api/client";

export type HubA2AAgentUserResponse = {
  id: string;
  name: string;
  card_url: string;
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
  contextId?: string;
  metadata?: Record<string, unknown>;
};

export type HubA2AAgentInvokeResponse = {
  success: boolean;
  content?: string | null;
  error?: string | null;
  error_code?: string | null;
  agent_name?: string | null;
  agent_url?: string | null;
};

export type HubWsTicketResponse = {
  token: string;
  expires_at: string;
  expires_in: number;
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
