import { apiRequest } from "@/lib/api/client";
import { parsePaginatedListResponse } from "@/lib/api/pagination";
import { type UnifiedSessionSource } from "@/lib/sessionIds";

export type SessionListItem = {
  conversationId: string;
  source: UnifiedSessionSource;
  external_provider?: string | null;
  external_session_id?: string | null;
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
  conversationId: string;
  source: UnifiedSessionSource;
  provider?: string | null;
  externalSessionId?: string | null;
  contextId?: string | null;
};

export const listSessionsPage = async (options?: {
  page?: number;
  size?: number;
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
      source?: UnifiedSessionSource;
    }
  >("/me/conversations:query", {
    method: "POST",
    body: {
      page,
      size,
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
  conversationId: string,
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
  >(`/me/conversations/${encodeURIComponent(conversationId)}/messages:query`, {
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
  conversationId: string,
): Promise<SessionContinueBinding> => {
  const response = await apiRequest<SessionContinueBinding>(
    `/me/conversations/${encodeURIComponent(conversationId)}:continue`,
    {
      method: "POST",
    },
  );
  return {
    ...response,
    conversationId: response.conversationId.trim(),
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
  };
};
