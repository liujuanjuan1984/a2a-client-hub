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
    chatPage: (sessionId: string, page: number) =>
      ["history", "chat", sessionId, page] as const,
    opencodePage: (
      agentId: string,
      sessionId: string,
      source: "personal" | "shared",
      page: number,
    ) => ["history", "opencode", source, agentId, sessionId, page] as const,
  },
  admin: {
    hubAgents: () => ["admin", "hub-agents"] as const,
    hubAgent: (id: string) => ["admin", "hub-agents", id] as const,
    invitations: () => ["admin", "invitations"] as const,
  },
};
