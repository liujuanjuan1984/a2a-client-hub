export const queryKeys = {
  me: () => ["auth", "me"] as const,
  agents: {
    catalog: () => ["agents", "catalog"] as const,
  },
  sessions: {
    directory: () => ["sessions", "directory"] as const,
    scheduledJobs: () => ["scheduled-jobs", "list"] as const,
    scheduledJobExecutions: (taskId: string) =>
      ["scheduled-jobs", "executions", taskId] as const,
  },
  history: {
    chat: (conversationId: string) =>
      ["history", "chat", conversationId] as const,
  },
  admin: {
    hubAgents: () => ["admin", "hub-agents"] as const,
    hubAgent: (id: string) => ["admin", "hub-agents", id] as const,
    hubAgentAllowlist: (id: string) =>
      ["admin", "hub-agents", id, "allowlist"] as const,
    invitations: () => ["admin", "invitations"] as const,
  },
};
