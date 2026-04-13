import { DEFAULT_API_KEY_HEADER } from "@/lib/agentHeaders";
import { type AgentConfig } from "@/store/agents";

export const createMockAgentConfig = (
  overrides: Partial<AgentConfig> = {},
): AgentConfig => ({
  id: "agent-1",
  source: "personal",
  name: "Agent One",
  cardUrl: "https://example.com/agent-1.json",
  authType: "none",
  bearerToken: "",
  apiKeyHeader: DEFAULT_API_KEY_HEADER,
  apiKeyValue: "",
  basicUsername: "",
  basicPassword: "",
  extraHeaders: [],
  invokeMetadataDefaults: [],
  status: "idle",
  ...overrides,
});
