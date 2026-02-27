import {
  type A2AAgentCardValidationResponse,
  type A2AAgentInvokeRequest,
  type A2AAgentInvokeResponse,
  type WsTicketResponse,
} from "@/lib/api/a2aAgents";
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

export const listHubAgents = (page = 1, size = 200) =>
  apiRequest<HubA2AAgentUserListResponse>("/a2a/agents", {
    query: { page, size },
  });

export const invokeHubAgent = (
  agentId: string,
  payload: A2AAgentInvokeRequest,
) =>
  apiRequest<A2AAgentInvokeResponse, A2AAgentInvokeRequest>(
    `/a2a/agents/${encodeURIComponent(agentId)}/invoke`,
    { method: "POST", body: payload },
  );

// These endpoints are expected to be added as part of hub streaming parity work.
export const getHubInvokeWsTicket = (agentId: string) =>
  apiRequest<WsTicketResponse>(
    `/a2a/agents/${encodeURIComponent(agentId)}/invoke/ws-token`,
    { method: "POST" },
  );

export const validateHubAgentCard = (agentId: string) =>
  apiRequest<A2AAgentCardValidationResponse>(
    `/a2a/agents/${encodeURIComponent(agentId)}/card:validate`,
    { method: "POST" },
  );
