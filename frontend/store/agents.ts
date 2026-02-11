import { create } from "zustand";
import { persist } from "zustand/middleware";

import { type AgentAuthType } from "@/lib/agentAuth";
import { type HeaderEntryWithId, headersToEntries } from "@/lib/agentHeaders";
import { buildAgentUpsertPayload } from "@/lib/agentUpsert";
import {
  createAgent,
  deleteAgent,
  listAgents,
  updateAgent,
  validateAgentCard,
  type A2AAgentResponse,
} from "@/lib/api/a2aAgents";
import {
  listHubAgents,
  validateHubAgentCard,
} from "@/lib/api/hubA2aAgentsUser";
import { createPersistStorage } from "@/lib/storage/mmkv";

export type AgentStatus = "idle" | "checking" | "success" | "error";

export type AgentHeader = HeaderEntryWithId;

export type AgentSource = "personal" | "shared";

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
};

export type AgentState = {
  agents: AgentConfig[];
  activeAgentId: string | null;
  hasLoaded: boolean;
  loadAgents: () => Promise<void>;
  addAgent: (
    payload: Omit<AgentConfig, "id" | "status" | "source">,
  ) => Promise<void>;
  updateAgent: (
    id: string,
    payload: Partial<Omit<AgentConfig, "id" | "source">>,
  ) => Promise<void>;
  removeAgent: (id: string) => Promise<void>;
  setActiveAgent: (id: string | null) => void;
  testAgent: (id: string) => Promise<void>;
  resetAgents: () => void;
};

const toAgentConfig = (agent: A2AAgentResponse): AgentConfig => ({
  id: agent.id,
  source: "personal",
  name: agent.name,
  cardUrl: agent.card_url,
  authType: agent.auth_type === "bearer" ? "bearer" : "none",
  bearerToken: "",
  apiKeyHeader: "X-API-Key",
  apiKeyValue: "",
  basicUsername: "",
  basicPassword: "",
  extraHeaders: headersToEntries(agent.extra_headers ?? {}),
  status: "idle",
});

const toSharedAgentConfig = (agent: {
  id: string;
  name: string;
  card_url: string;
  tags?: string[];
}): AgentConfig => ({
  id: agent.id,
  source: "shared",
  name: agent.name,
  cardUrl: agent.card_url,
  authType: "none",
  bearerToken: "",
  apiKeyHeader: "X-API-Key",
  apiKeyValue: "",
  basicUsername: "",
  basicPassword: "",
  extraHeaders: [],
  status: "idle",
});

export const useAgentStore = create<AgentState>()(
  persist(
    (set, get) => ({
      agents: [],
      activeAgentId: null,
      hasLoaded: false,
      loadAgents: async () => {
        const previousAgents = get().agents;
        const results = await Promise.allSettled([
          listAgents(1, 200),
          listHubAgents(1, 200),
        ]);

        const personal =
          results[0].status === "fulfilled"
            ? results[0].value.items.map(toAgentConfig)
            : previousAgents.filter((agent) => agent.source === "personal");
        const shared =
          results[1].status === "fulfilled"
            ? results[1].value.items.map(toSharedAgentConfig)
            : previousAgents.filter((agent) => agent.source === "shared");

        const agents = [...personal, ...shared];

        set((state) => ({
          agents,
          activeAgentId: agents.some((item) => item.id === state.activeAgentId)
            ? state.activeAgentId
            : null,
          hasLoaded: true,
        }));

        if (
          results[0].status === "rejected" &&
          results[1].status === "rejected"
        ) {
          throw results[0].reason ?? results[1].reason;
        }
      },
      addAgent: async (payload) => {
        const request = buildAgentUpsertPayload({
          name: payload.name,
          cardUrl: payload.cardUrl,
          authType: payload.authType,
          bearerToken: payload.bearerToken,
          apiKeyHeader: payload.apiKeyHeader,
          apiKeyValue: payload.apiKeyValue,
          basicUsername: payload.basicUsername,
          basicPassword: payload.basicPassword,
          extraHeaders: payload.extraHeaders,
        });
        const response = await createAgent(request);
        set((state) => ({
          agents: [toAgentConfig(response), ...state.agents],
        }));
      },
      updateAgent: async (id, payload) => {
        const existing = get().agents.find((agent) => agent.id === id);
        if (!existing) {
          throw new Error("Agent not found.");
        }
        if (existing.source !== "personal") {
          throw new Error(
            "This agent is managed by an admin and cannot be edited.",
          );
        }
        const next = { ...existing, ...payload };
        const request = buildAgentUpsertPayload({
          name: next.name,
          cardUrl: next.cardUrl,
          authType: next.authType,
          bearerToken: next.bearerToken,
          apiKeyHeader: next.apiKeyHeader,
          apiKeyValue: next.apiKeyValue,
          basicUsername: next.basicUsername,
          basicPassword: next.basicPassword,
          extraHeaders: next.extraHeaders,
        });
        const response = await updateAgent(id, request);
        set((state) => ({
          agents: state.agents.map((agent) =>
            agent.id === id
              ? { ...toAgentConfig(response), status: agent.status }
              : agent,
          ),
        }));
      },
      removeAgent: async (id) => {
        const existing = get().agents.find((agent) => agent.id === id);
        if (existing && existing.source !== "personal") {
          throw new Error(
            "This agent is managed by an admin and cannot be removed.",
          );
        }
        await deleteAgent(id);
        set((state) => ({
          agents: state.agents.filter((agent) => agent.id !== id),
          activeAgentId:
            state.activeAgentId === id ? null : state.activeAgentId,
        }));
      },
      setActiveAgent: (id) => set({ activeAgentId: id }),
      testAgent: async (id) => {
        const agent = get().agents.find((item) => item.id === id);
        if (!agent) {
          return;
        }

        set((state) => ({
          agents: state.agents.map((item) =>
            item.id === id
              ? { ...item, status: "checking", lastError: undefined }
              : item,
          ),
        }));

        try {
          const response =
            agent.source === "shared"
              ? await validateHubAgentCard(id)
              : await validateAgentCard(id);
          if (!response.success) {
            const rawMessage =
              response.validation_errors?.[0] || response.message;
            const errorMessage =
              typeof rawMessage === "string"
                ? rawMessage
                : rawMessage
                  ? JSON.stringify(rawMessage)
                  : "Connection failed";
            throw new Error(errorMessage);
          }
          set((state) => ({
            agents: state.agents.map((item) =>
              item.id === id
                ? {
                    ...item,
                    status: "success",
                    lastCheckedAt: new Date().toISOString(),
                    lastError: undefined,
                  }
                : item,
            ),
          }));
        } catch (error) {
          const message =
            error instanceof Error ? error.message : "Connection failed";
          set((state) => ({
            agents: state.agents.map((item) =>
              item.id === id
                ? {
                    ...item,
                    status: "error",
                    lastCheckedAt: new Date().toISOString(),
                    lastError: message,
                  }
                : item,
            ),
          }));
        }
      },
      resetAgents: () =>
        set({ agents: [], activeAgentId: null, hasLoaded: false }),
    }),
    {
      name: "a2a-client-hub.agents",
      storage: createPersistStorage(),
      partialize: (state) => ({
        agents: state.agents
          .filter((agent) => agent.source === "personal")
          .map((agent) => {
            const { status, lastError, ...rest } = agent;
            return rest;
          }),
        activeAgentId: state.activeAgentId,
      }),
    },
  ),
);
