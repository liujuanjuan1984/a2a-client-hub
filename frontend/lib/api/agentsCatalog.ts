import { apiRequest } from "@/lib/api/client";

export type UnifiedAgentSource = "personal" | "shared" | "builtin";
export type UnifiedAgentHealthStatus =
  | "unknown"
  | "healthy"
  | "degraded"
  | "unavailable";
export type UnifiedAgentHealthReasonCode =
  | "card_validation_failed"
  | "runtime_validation_failed"
  | "agent_unavailable"
  | "client_reset_required"
  | "credential_required"
  | "unexpected_error";

export type UnifiedAgentCatalogItemResponse = {
  id: string;
  source: UnifiedAgentSource;
  name: string;
  card_url: string;
  auth_type: "none" | "bearer" | "basic";
  enabled: boolean;
  health_status: UnifiedAgentHealthStatus;
  last_health_check_at?: string | null;
  last_health_check_error?: string | null;
  last_health_check_reason_code?: UnifiedAgentHealthReasonCode | null;
  credential_mode?: "none" | "shared" | "user" | null;
  credential_configured?: boolean | null;
  credential_display_hint?: string | null;
  description?: string | null;
  runtime?: string | null;
  resources?: string[] | null;
  extra_headers?: Record<string, string> | null;
  invoke_metadata_defaults?: Record<string, string> | null;
};

export type UnifiedAgentCatalogResponse = {
  items: UnifiedAgentCatalogItemResponse[];
};

export type UnifiedAgentHealthCheckResponse = {
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
    agent_source: UnifiedAgentSource;
    health_status: UnifiedAgentHealthStatus;
    checked_at: string;
    skipped_cooldown: boolean;
    error?: string | null;
    reason_code?: UnifiedAgentHealthReasonCode | null;
  }[];
};

export const listAgentsCatalog = () =>
  apiRequest<UnifiedAgentCatalogResponse>("/me/agents/catalog");

export const checkAgentsCatalogHealth = (force = false) =>
  apiRequest<UnifiedAgentHealthCheckResponse>("/me/agents/check-health", {
    method: "POST",
    query: { force: force ? "true" : "false" },
  });
