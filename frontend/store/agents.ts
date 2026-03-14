import { create } from "zustand";
import { persist } from "zustand/middleware";

import { type AgentAuthType } from "@/lib/agentAuth";
import { type HeaderEntryWithId } from "@/lib/agentHeaders";
import { createPersistStorage } from "@/lib/storage/mmkv";

export type AgentStatus = "idle" | "checking" | "success" | "error";

export type AgentHeader = HeaderEntryWithId;

export type AgentSource = "personal" | "shared";

export type AgentSessionBindingWriteMode =
  | "declared_contract"
  | "compat_fallback"
  | "unknown";

export type AgentSessionBindingCapability = {
  declared: boolean;
  mode: AgentSessionBindingWriteMode;
  uri?: string | null;
  metadataField?: string | null;
};

export type AgentCapabilities = {
  sessionBinding?: AgentSessionBindingCapability | null;
};

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
  status: AgentStatus;
  lastCheckedAt?: string;
  lastError?: string;
  capabilities?: AgentCapabilities | null;
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
      name: "a2a-client-hub.agents",
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
