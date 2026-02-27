import { apiRequest } from "@/lib/api/client";

export type A2AProxyAllowlistResponse = {
  id: string;
  host_pattern: string;
  is_enabled: boolean;
  remark?: string | null;
  created_at: string;
  updated_at: string;
};

export type A2AProxyAllowlistCreate = {
  host_pattern: string;
  is_enabled?: boolean;
  remark?: string | null;
};

export type A2AProxyAllowlistUpdate = {
  host_pattern?: string;
  is_enabled?: boolean;
  remark?: string | null;
};

export const listProxyAllowlist = () =>
  apiRequest<A2AProxyAllowlistResponse[]>("/admin/proxy/allowlist");

export const createProxyAllowlistEntry = (payload: A2AProxyAllowlistCreate) =>
  apiRequest<A2AProxyAllowlistResponse, A2AProxyAllowlistCreate>(
    "/admin/proxy/allowlist",
    { method: "POST", body: payload },
  );

export const updateProxyAllowlistEntry = (
  entryId: string,
  payload: A2AProxyAllowlistUpdate,
) =>
  apiRequest<A2AProxyAllowlistResponse, A2AProxyAllowlistUpdate>(
    `/admin/proxy/allowlist/${encodeURIComponent(entryId)}`,
    { method: "PATCH", body: payload },
  );

export const deleteProxyAllowlistEntry = (entryId: string) =>
  apiRequest<void>(`/admin/proxy/allowlist/${encodeURIComponent(entryId)}`, {
    method: "DELETE",
  });
