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

export type SessionMessageBlocksItem = {
  messageId: string;
  role: "user" | "agent" | "system";
  blockCount: number;
  hasBlocks: boolean;
  blocks: SessionMessageBlockItem[];
};

export type SessionMessageItem = {
  id: string;
  role: "user" | "agent" | "system";
  created_at: string;
  metadata?: Record<string, unknown> | null;
  blocks?: SessionMessageBlockItem[];
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

export const querySessionMessageBlocks = async (
  conversationId: string,
  payload: {
    messageIds: string[];
    mode?: "full" | "text_with_placeholders" | "outline";
  },
): Promise<{
  items: SessionMessageBlocksItem[];
  meta?: Record<string, unknown>;
}> => {
  const response = await apiRequest<
    {
      items: SessionMessageBlocksItem[];
      meta?: Record<string, unknown>;
    },
    {
      messageIds: string[];
      mode: "full" | "text_with_placeholders" | "outline";
    }
  >(
    `/me/conversations/${encodeURIComponent(conversationId)}/messages/blocks:query`,
    {
      method: "POST",
      body: {
        messageIds: payload.messageIds,
        mode: payload.mode ?? "full",
      },
    },
  );

  return {
    items: Array.isArray(response.items) ? response.items : [],
    meta:
      response.meta && typeof response.meta === "object"
        ? response.meta
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
