export const queryKeys = {
  me: () => ["auth", "me"] as const,
  agents: {
    catalog: () => ["agents", "catalog"] as const,
  },
  sessions: {
    directory: () => ["sessions", "directory"] as const,
    opencodeByAgent: (agentId: string, source: "personal" | "shared") =>
      ["sessions", "opencode", source, agentId] as const,
    scheduledJobs: () => ["scheduled-jobs", "list"] as const,
  },
  history: {
    chat: (sessionId: string) => ["history", "chat", sessionId] as const,
    opencode: (
      agentId: string,
      sessionId: string,
      source: "personal" | "shared",
    ) => ["history", "opencode", source, agentId, sessionId] as const,
  },
  admin: {
    hubAgents: () => ["admin", "hub-agents"] as const,
    hubAgent: (id: string) => ["admin", "hub-agents", id] as const,
    invitations: () => ["admin", "invitations"] as const,
  },
};
