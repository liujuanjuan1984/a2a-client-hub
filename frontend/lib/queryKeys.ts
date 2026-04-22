export const queryKeys = {
  me: () => ["auth", "me"] as const,
  agents: {
    catalog: () => ["agents", "catalog"] as const,
    listRoot: () => ["agents", "list"] as const,
    list: (filters?: {
      page?: number;
      size?: number;
      healthBucket?: string;
    }) => {
      const resolvedFilters: Record<string, string | number> = {};
      if (
        typeof filters?.page === "number" &&
        Number.isFinite(filters.page) &&
        filters.page > 0
      ) {
        resolvedFilters.page = Math.floor(filters.page);
      }
      if (
        typeof filters?.size === "number" &&
        Number.isFinite(filters.size) &&
        filters.size > 0
      ) {
        resolvedFilters.size = Math.floor(filters.size);
      }
      if (
        typeof filters?.healthBucket === "string" &&
        filters.healthBucket.trim()
      ) {
        resolvedFilters.health_bucket = filters.healthBucket.trim();
      }
      return Object.keys(resolvedFilters).length > 0
        ? (["agents", "list", resolvedFilters] as const)
        : (["agents", "list"] as const);
    },
    sharedListRoot: () => ["agents", "shared-list"] as const,
    sharedList: (filters?: { page?: number; size?: number }) => {
      const resolvedFilters: Record<string, number> = {};
      if (
        typeof filters?.page === "number" &&
        Number.isFinite(filters.page) &&
        filters.page > 0
      ) {
        resolvedFilters.page = Math.floor(filters.page);
      }
      if (
        typeof filters?.size === "number" &&
        Number.isFinite(filters.size) &&
        filters.size > 0
      ) {
        resolvedFilters.size = Math.floor(filters.size);
      }
      return Object.keys(resolvedFilters).length > 0
        ? (["agents", "shared-list", resolvedFilters] as const)
        : (["agents", "shared-list"] as const);
    },
    extensionCapabilities: (input: {
      agentId: string;
      source: "personal" | "shared";
    }) =>
      [
        "agents",
        "extension-capabilities",
        input.source,
        input.agentId,
      ] as const,
  },
  schedules: {
    listRoot: () => ["scheduled-jobs", "list"] as const,
    list: (filters?: Record<string, unknown>) =>
      filters
        ? (["scheduled-jobs", "list", filters] as const)
        : (["scheduled-jobs", "list"] as const),
    executionsRoot: (taskId?: string) =>
      taskId
        ? (["scheduled-jobs", "executions", taskId] as const)
        : (["scheduled-jobs", "executions"] as const),
    executions: (
      taskId: string,
      options?: {
        page?: number;
      },
    ) =>
      typeof options?.page === "number"
        ? (["scheduled-jobs", "executions", taskId, options.page] as const)
        : (["scheduled-jobs", "executions", taskId] as const),
  },
  sessions: {
    directory: (filters?: {
      source?: string;
      agentId?: string;
      size?: number;
    }) => {
      const resolvedFilters: Record<string, string | number> = {};
      if (typeof filters?.source === "string" && filters.source.trim()) {
        resolvedFilters.source = filters.source.trim();
      }
      if (typeof filters?.agentId === "string" && filters.agentId.trim()) {
        resolvedFilters.agent_id = filters.agentId.trim();
      }
      if (
        typeof filters?.size === "number" &&
        Number.isFinite(filters.size) &&
        filters.size > 0
      ) {
        resolvedFilters.size = Math.floor(filters.size);
      }
      return Object.keys(resolvedFilters).length > 0
        ? (["sessions", "directory", resolvedFilters] as const)
        : (["sessions", "directory"] as const);
    },
    scheduledJobs: () => ["scheduled-jobs", "list"] as const,
    scheduledJobExecutions: (taskId: string) =>
      ["scheduled-jobs", "executions", taskId] as const,
    upstreamTask: (conversationId: string, taskId: string) =>
      ["sessions", "upstream-task", conversationId, taskId] as const,
  },
  history: {
    chat: (conversationId: string) =>
      ["history", "chat", conversationId] as const,
  },
  shortcuts: {
    list: () => ["shortcuts", "list"] as const,
  },
  admin: {
    hubAgents: () => ["admin", "hub-agents"] as const,
    hubAgent: (id: string) => ["admin", "hub-agents", id] as const,
    hubAgentAllowlist: (id: string) =>
      ["admin", "hub-agents", id, "allowlist"] as const,
    invitations: () => ["admin", "invitations"] as const,
    proxyAllowlist: () => ["admin", "proxy-allowlist"] as const,
  },
};
