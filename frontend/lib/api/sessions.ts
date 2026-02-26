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

export type SessionMessageBlockItem = {
  id: string;
  messageId: string;
  seq: number;
  type: string;
  content?: string | null;
  contentLength: number;
  isFinished: boolean;
};

export type SessionMessageItem = {
  id: string;
  role: "user" | "agent" | "system";
  created_at: string;
  status?: string;
  metadata?: Record<string, unknown> | null;
  blocks?: SessionMessageBlockItem[];
};

export type SessionTimelinePageInfo = {
  hasMoreBefore: boolean;
  nextBefore?: string | null;
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
  agent_id?: string;
}) => {
  const page = options?.page ?? 1;
  const size = options?.size ?? 50;
  const agentId =
    typeof options?.agent_id === "string" && options.agent_id.trim().length > 0
      ? options.agent_id.trim()
      : null;
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
      agent_id?: string;
    }
  >("/me/conversations:query", {
    method: "POST",
    body: {
      page,
      size,
      ...(options?.source ? { source: options.source } : {}),
      ...(agentId ? { agent_id: agentId } : {}),
    },
  });

  const parsed = parsePaginatedListResponse(response);
  const nextPage = resolveNextPageWithFallback({ parsed, page, size });
  return { ...parsed, nextPage };
};

export const listSessionTimelinePage = async (
  conversationId: string,
  options?: { before?: string | null; limit?: number },
) => {
  const limit = options?.limit ?? 8;
  const before =
    typeof options?.before === "string" && options.before.trim().length > 0
      ? options.before.trim()
      : null;
  const response = await apiRequest<
    {
      items: SessionMessageItem[];
      pageInfo?: SessionTimelinePageInfo;
      meta?: unknown;
    },
    {
      before?: string;
      limit: number;
    }
  >(
    `/me/conversations/${encodeURIComponent(conversationId)}/messages/timeline:query`,
    {
      method: "POST",
      body: {
        ...(before ? { before } : {}),
        limit,
      },
    },
  );

  const resolvedItems = Array.isArray(response.items) ? response.items : [];
  const resolvedPageInfo =
    response.pageInfo &&
    typeof response.pageInfo === "object" &&
    response.pageInfo.hasMoreBefore === true
      ? {
          hasMoreBefore: true,
          nextBefore:
            typeof response.pageInfo.nextBefore === "string"
              ? response.pageInfo.nextBefore
              : null,
        }
      : {
          hasMoreBefore: false,
          nextBefore:
            response.pageInfo &&
            typeof response.pageInfo === "object" &&
            typeof response.pageInfo.nextBefore === "string"
              ? response.pageInfo.nextBefore
              : null,
        };

  return {
    items: resolvedItems,
    pageInfo: resolvedPageInfo,
    meta:
      response.meta && typeof response.meta === "object"
        ? (response.meta as Record<string, unknown>)
        : undefined,
  };
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
