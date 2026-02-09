export const queryKeys = {
  me: (token?: string | null) => ["auth", "me", token ?? "anonymous"] as const,
  admin: {
    hubAgents: () => ["admin", "hub-agents"] as const,
    hubAgent: (id: string) => ["admin", "hub-agents", id] as const,
  },
};
