import { apiRequest } from "@/lib/api/client";
import {
  parsePaginatedListResponse,
  resolveNextPageWithFallback,
} from "@/lib/api/pagination";
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
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  created_at: string;
  metadata?: Record<string, unknown> | null;
};

export type SessionContinueBinding = {
  conversationId: string;
  source: UnifiedSessionSource;
  metadata?: Record<string, unknown> | null;
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
  const nextPage = resolveNextPageWithFallback({ parsed, page, size });
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
  const nextPage = resolveNextPageWithFallback({ parsed, page, size });

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
    metadata:
      typeof response.metadata === "object" && response.metadata !== null
        ? (response.metadata as Record<string, unknown>)
        : null,
  };
};
