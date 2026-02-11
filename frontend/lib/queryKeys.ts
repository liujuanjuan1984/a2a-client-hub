export const queryKeys = {
  me: () => ["auth", "me"] as const,
  admin: {
    hubAgents: () => ["admin", "hub-agents"] as const,
    hubAgent: (id: string) => ["admin", "hub-agents", id] as const,
  },
};
