import { apiRequest } from "@/lib/api/client";

export type HubA2AAvailabilityPolicy = "public" | "allowlist";
export type HubA2AAuthType = "none" | "bearer" | "basic";
export type HubA2ACredentialMode = "none" | "shared" | "user";

export type HubA2AAgentAdminResponse = {
  id: string;
  name: string;
  card_url: string;
  availability_policy: HubA2AAvailabilityPolicy;
  auth_type: HubA2AAuthType;
  auth_header?: string | null;
  auth_scheme?: string | null;
  credential_mode: HubA2ACredentialMode;
  enabled: boolean;
  tags: string[];
  extra_headers: Record<string, string>;
  invoke_metadata_defaults: Record<string, string>;
  has_credential: boolean;
  token_last4?: string | null;
  username_hint?: string | null;
  created_by_user_id: string;
  updated_by_user_id?: string | null;
  created_at: string;
  updated_at: string;
};

type HubA2AAgentAdminListResponse = {
  items: HubA2AAgentAdminResponse[];
  pagination: {
    page: number;
    size: number;
    total: number;
    pages: number;
  };
  meta: Record<string, unknown>;
};

export type HubA2AAgentAdminCreate = {
  name: string;
  card_url: string;
  availability_policy: HubA2AAvailabilityPolicy;
  auth_type: HubA2AAuthType;
  auth_header?: string | null;
  auth_scheme?: string | null;
  credential_mode: HubA2ACredentialMode;
  enabled: boolean;
  tags: string[];
  extra_headers: Record<string, string>;
  invoke_metadata_defaults: Record<string, string>;
  token?: string | null;
  basic_username?: string | null;
  basic_password?: string | null;
};

type HubA2AAgentAdminUpdate = Partial<HubA2AAgentAdminCreate>;

export type HubA2AAllowlistEntryResponse = {
  id: string;
  agent_id: string;
  user_id: string;
  user_email?: string | null;
  user_name?: string | null;
  created_by_user_id: string;
  created_at: string;
};

type HubA2AAllowlistListResponse = {
  items: HubA2AAllowlistEntryResponse[];
};

type HubA2AAllowlistAddRequest = {
  user_id?: string | null;
  email?: string | null;
};

export const listHubAgentsAdmin = (page = 1, size = 200) =>
  apiRequest<HubA2AAgentAdminListResponse>("/admin/a2a/agents", {
    query: { page, size },
  });

export const getHubAgentAdmin = (agentId: string) =>
  apiRequest<HubA2AAgentAdminResponse>(
    `/admin/a2a/agents/${encodeURIComponent(agentId)}`,
  );

export const createHubAgentAdmin = (payload: HubA2AAgentAdminCreate) =>
  apiRequest<HubA2AAgentAdminResponse, HubA2AAgentAdminCreate>(
    "/admin/a2a/agents",
    { method: "POST", body: payload },
  );

export const updateHubAgentAdmin = (
  agentId: string,
  payload: HubA2AAgentAdminUpdate,
) =>
  apiRequest<HubA2AAgentAdminResponse, HubA2AAgentAdminUpdate>(
    `/admin/a2a/agents/${encodeURIComponent(agentId)}`,
    { method: "PUT", body: payload },
  );

export const deleteHubAgentAdmin = (agentId: string) =>
  apiRequest<void>(`/admin/a2a/agents/${encodeURIComponent(agentId)}`, {
    method: "DELETE",
  });

export const listHubAgentAllowlistAdmin = (agentId: string) =>
  apiRequest<HubA2AAllowlistListResponse>(
    `/admin/a2a/agents/${encodeURIComponent(agentId)}/allowlist`,
  );

export const addHubAgentAllowlistAdmin = (
  agentId: string,
  payload: HubA2AAllowlistAddRequest,
) =>
  apiRequest<void, HubA2AAllowlistAddRequest>(
    `/admin/a2a/agents/${encodeURIComponent(agentId)}/allowlist`,
    { method: "POST", body: payload },
  );

export const deleteHubAgentAllowlistEntryAdmin = (
  agentId: string,
  userId: string,
) =>
  apiRequest<void>(
    `/admin/a2a/agents/${encodeURIComponent(agentId)}/allowlist/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );
