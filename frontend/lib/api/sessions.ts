import {
  type RuntimeInterrupt,
  type ToolCallDetailView,
  type ToolCallView,
} from "@/lib/api/chat-utils";
import { apiRequest } from "@/lib/api/client";
import {
  parsePaginatedListResponse,
  resolveNextPageWithFallback,
} from "@/lib/api/pagination";
import { type UnifiedSessionSource } from "@/lib/sessionIds";
import { normalizeWorkingDirectory } from "@/lib/workingDirectory";

export type SessionListItem = {
  conversationId: string;
  source: UnifiedSessionSource;
  external_provider?: string | null;
  external_session_id?: string | null;
  agent_id?: string | null;
  agent_source?: "personal" | "shared" | "builtin" | null;
  title: string;
  last_active_at?: string | null;
  created_at?: string | null;
};

type SessionMessageBlockItem = {
  id: string;
  type: string;
  content?: string | null;
  isFinished: boolean;
  blockId?: string | null;
  laneId?: string | null;
  baseSeq?: number | null;
  toolCall?: ToolCallView | null;
  interrupt?: RuntimeInterrupt | null;
};

type SessionMessageBlockDetailItem = {
  id: string;
  messageId: string;
  type: string;
  content?: string | null;
  isFinished: boolean;
  blockId?: string | null;
  laneId?: string | null;
  baseSeq?: number | null;
  toolCall?: ToolCallView | null;
  toolCallDetail?: ToolCallDetailView | null;
  interrupt?: RuntimeInterrupt | null;
};

export type SessionMessageItem = {
  id: string;
  role: "user" | "agent" | "system";
  content?: string;
  created_at: string;
  status?: string;
  blocks?: SessionMessageBlockItem[];
};

type SessionMessagesPageInfo = {
  hasMoreBefore: boolean;
  nextBefore?: string | null;
};

export type SessionContinueBinding = {
  conversationId: string;
  source: UnifiedSessionSource;
  metadata?: Record<string, unknown> | null;
  workingDirectory?: string | null;
};

export type SessionCancelResult = {
  conversationId: string;
  taskId?: string | null;
  cancelled: boolean;
  status: "accepted" | "pending" | "no_inflight" | "already_terminal";
};

export type SessionControlResult = {
  intent: "append" | "preempt";
  status: "accepted" | "completed" | "no_inflight" | "unavailable" | "failed";
  sessionId?: string | null;
};

export type SessionAppendMessageResult = {
  conversationId: string;
  userMessage: SessionMessageItem;
  sessionControl: SessionControlResult;
};

export type SessionCommandRunResult = {
  conversationId: string;
  userMessage: SessionMessageItem;
  agentMessage: SessionMessageItem;
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
      pageInfo?: SessionMessagesPageInfo;
    },
    {
      before?: string;
      limit: number;
    }
  >(`/me/conversations/${encodeURIComponent(conversationId)}/messages:query`, {
    method: "POST",
    body: {
      ...(before ? { before } : {}),
      limit,
    },
  });

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
  };
};

export const querySessionMessageBlocks = async (
  conversationId: string,
  options: { blockIds: string[] },
) => {
  const blockIds = Array.isArray(options.blockIds)
    ? options.blockIds
        .map((value) => (typeof value === "string" ? value.trim() : ""))
        .filter((value) => value.length > 0)
    : [];
  if (blockIds.length === 0) {
    return { items: [] as SessionMessageBlockDetailItem[] };
  }
  const response = await apiRequest<
    { items?: SessionMessageBlockDetailItem[] },
    { blockIds: string[] }
  >(`/me/conversations/${encodeURIComponent(conversationId)}/blocks:query`, {
    method: "POST",
    body: {
      blockIds,
    },
  });
  return {
    items: Array.isArray(response.items) ? response.items : [],
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
    workingDirectory: normalizeWorkingDirectory(response.workingDirectory),
  };
};

export const cancelSession = async (
  conversationId: string,
): Promise<SessionCancelResult> =>
  apiRequest<SessionCancelResult>(
    `/me/conversations/${encodeURIComponent(conversationId)}/cancel`,
    {
      method: "POST",
    },
  );

export const appendSessionMessage = async (
  conversationId: string,
  input: {
    content: string;
    userMessageId?: string;
    metadata?: Record<string, unknown>;
    workingDirectory?: string | null;
  },
): Promise<SessionAppendMessageResult> =>
  apiRequest<
    SessionAppendMessageResult,
    {
      content: string;
      userMessageId?: string;
      metadata?: Record<string, unknown>;
      workingDirectory?: string | null;
    }
  >(`/me/conversations/${encodeURIComponent(conversationId)}/messages:append`, {
    method: "POST",
    body: {
      content: input.content,
      ...(input.userMessageId ? { userMessageId: input.userMessageId } : {}),
      ...(input.metadata ? { metadata: input.metadata } : {}),
      ...(input.workingDirectory
        ? { workingDirectory: input.workingDirectory }
        : {}),
    },
  });

export const runSessionCommand = async (
  conversationId: string,
  input: {
    command: string;
    arguments: string;
    prompt: string;
    userMessageId?: string;
    agentMessageId?: string;
    metadata?: Record<string, unknown>;
    workingDirectory?: string | null;
  },
): Promise<SessionCommandRunResult> =>
  apiRequest<
    SessionCommandRunResult,
    {
      command: string;
      arguments: string;
      prompt: string;
      userMessageId?: string;
      agentMessageId?: string;
      metadata?: Record<string, unknown>;
      workingDirectory?: string | null;
    }
  >(`/me/conversations/${encodeURIComponent(conversationId)}/commands:run`, {
    method: "POST",
    body: {
      command: input.command,
      arguments: input.arguments,
      prompt: input.prompt,
      ...(input.userMessageId ? { userMessageId: input.userMessageId } : {}),
      ...(input.agentMessageId ? { agentMessageId: input.agentMessageId } : {}),
      ...(input.metadata ? { metadata: input.metadata } : {}),
      ...(input.workingDirectory
        ? { workingDirectory: input.workingDirectory }
        : {}),
    },
  });
