import { create } from "zustand";
import { persist } from "zustand/middleware";

import { type AgentAuthType } from "@/lib/agentAuth";
import { type HeaderEntryWithId } from "@/lib/agentHeaders";
import {
  buildPersistStorageName,
  createPersistStorage,
} from "@/lib/storage/mmkv";

type AgentStatus = "idle" | "checking" | "success" | "error";

export type AgentHeader = HeaderEntryWithId;

export type AgentSource = "personal" | "shared" | "hub_assistant";

export type AgentConfig = {
  id: string;
  source: AgentSource;
  name: string;
  cardUrl: string;
  authType: AgentAuthType;
  bearerToken: string;
  apiKeyHeader: string;
  apiKeyValue: string;
  basicUsername: string;
  basicPassword: string;
  extraHeaders: AgentHeader[];
  invokeMetadataDefaults: AgentHeader[];
  status: AgentStatus;
  lastCheckedAt?: string;
  lastError?: string;
  enabled?: boolean;
  healthStatus?: "unknown" | "healthy" | "degraded" | "unavailable";
  lastHealthCheckAt?: string;
  lastHealthCheckError?: string;
  lastHealthCheckReasonCode?:
    | "card_validation_failed"
    | "runtime_validation_failed"
    | "agent_unavailable"
    | "client_reset_required"
    | "credential_required"
    | "unexpected_error";
  credentialMode?: "none" | "shared" | "user";
  credentialConfigured?: boolean;
  credentialDisplayHint?: string;
  description?: string;
  runtime?: string;
  resources?: string[];
};

type AgentState = {
  activeAgentId: string | null;
  setActiveAgent: (id: string | null) => void;
  resetAgentUiState: () => void;
};

export const useAgentStore = create<AgentState>()(
  persist(
    (set) => ({
      activeAgentId: null,
      setActiveAgent: (id) => set({ activeAgentId: id }),
      resetAgentUiState: () => set({ activeAgentId: null }),
    }),
    {
      name: buildPersistStorageName("a2a-client-hub.agents", "web_tab"),
      storage: createPersistStorage(),
      version: 2,
      migrate: (persistedState) => {
        const raw = (persistedState ?? {}) as {
          activeAgentId?: unknown;
        };
        return {
          activeAgentId:
            typeof raw.activeAgentId === "string" ? raw.activeAgentId : null,
        };
      },
      partialize: (state) => ({
        activeAgentId: state.activeAgentId,
      }),
    },
  ),
);
