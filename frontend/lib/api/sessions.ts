import { apiRequest } from "@/lib/api/client";
import { parsePaginatedListResponse } from "@/lib/api/pagination";
import { type UnifiedSessionSource } from "@/lib/sessionIds";

export type SessionListItem = {
  id: string;
  conversationId?: string | null;
  source: UnifiedSessionSource;
  source_session_id: string;
  agent_id?: string | null;
  agent_source?: "personal" | "shared" | null;
  title: string;
  last_active_at?: string | null;
  created_at?: string | null;
};

export type SessionMessageItem = {
  id?: string;
  role: "user" | "agent" | "system";
  content: string;
  created_at: string;
  metadata?: Record<string, unknown> | null;
};

export type SessionContinueBinding = {
  session_id: string;
  conversationId?: string | null;
  source: UnifiedSessionSource;
  provider?: string | null;
  externalSessionId?: string | null;
  contextId?: string | null;
  metadata: Record<string, unknown>;
};

export const listSessionsPage = async (options?: {
  page?: number;
  size?: number;
  refresh?: boolean;
  source?: UnifiedSessionSource;
}) => {
  const page = options?.page ?? 1;
  const size = options?.size ?? 50;
  const response = await apiRequest<
    {
      items: SessionListItem[];
      pagination?: unknown;
      meta?: unknown;
    },
    {
      page: number;
      size: number;
      refresh: boolean;
      source?: UnifiedSessionSource;
    }
  >("/me/sessions:query", {
    method: "POST",
    body: {
      page,
      size,
      refresh: options?.refresh ?? false,
      ...(options?.source ? { source: options.source } : {}),
    },
  });

  const parsed = parsePaginatedListResponse(response);
  const pagination =
    parsed.pagination && typeof parsed.pagination === "object"
      ? (parsed.pagination as Record<string, unknown>)
      : {};
  const pages = typeof pagination.pages === "number" ? pagination.pages : 0;
  const nextPage = pages > 0 && page < pages ? page + 1 : undefined;
  return { ...parsed, nextPage };
};

export const listSessionMessagesPage = async (
  sessionId: string,
  options?: { page?: number; size?: number },
) => {
  const page = options?.page ?? 1;
  const size = options?.size ?? 100;
  const response = await apiRequest<
    {
      items: SessionMessageItem[];
      pagination?: unknown;
      meta?: unknown;
    },
    { page: number; size: number }
  >(`/me/sessions/${encodeURIComponent(sessionId)}/messages:query`, {
    method: "POST",
    body: { page, size },
  });

  const parsed = parsePaginatedListResponse(response);
  const nextPage =
    typeof parsed.nextPage === "number"
      ? parsed.nextPage
      : parsed.items.length >= size
        ? page + 1
        : undefined;

  return { ...parsed, nextPage };
};

export const continueSession = async (
  sessionId: string,
): Promise<SessionContinueBinding> => {
  const response = await apiRequest<SessionContinueBinding>(
    `/me/sessions/${encodeURIComponent(sessionId)}:continue`,
    {
      method: "POST",
    },
  );
  return {
    ...response,
    conversationId:
      typeof response.conversationId === "string" &&
      response.conversationId.trim()
        ? response.conversationId.trim()
        : null,
    provider:
      typeof response.provider === "string" && response.provider.trim()
        ? response.provider.trim()
        : null,
    externalSessionId:
      typeof response.externalSessionId === "string" &&
      response.externalSessionId.trim()
        ? response.externalSessionId.trim()
        : null,
    contextId:
      typeof response.contextId === "string" && response.contextId.trim()
        ? response.contextId.trim()
        : null,
    metadata:
      response.metadata && typeof response.metadata === "object"
        ? response.metadata
        : {},
  };
};
