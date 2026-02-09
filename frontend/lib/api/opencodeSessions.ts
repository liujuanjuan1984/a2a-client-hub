import {
  assertExtensionSuccess,
  type A2AExtensionQueryRequest,
  type A2AExtensionResponse,
} from "@/lib/api/a2aExtensions";
import { apiRequest } from "@/lib/api/client";
import {
  type PaginatedResult,
  parsePaginatedListResponse,
} from "@/lib/api/pagination";

type AgentSource = "personal" | "shared";

type OpencodeResultEnvelope = {
  items?: unknown[];
  pagination?: unknown;
  meta?: unknown;
  raw?: unknown;
  [key: string]: unknown;
};

export type OpencodePaginatedResult = PaginatedResult<unknown> & {
  envelope: OpencodeResultEnvelope;
  raw: unknown;
};

const normalizeEnvelope = (value: Record<string, unknown> | null | undefined) =>
  (value ?? {}) as OpencodeResultEnvelope;

const extractItems = (envelope: OpencodeResultEnvelope): unknown[] => {
  if (Array.isArray(envelope.items)) return envelope.items;
  if (Array.isArray(envelope.raw)) return envelope.raw;
  return [];
};

const scopeForSource = (source: AgentSource) =>
  source === "shared" ? "/a2a/agents" : "/me/a2a/agents";

export type OpencodeContinueBinding = {
  contextId: string | null;
  metadata: Record<string, unknown>;
  raw: unknown;
};

const parseContinueBinding = (value: unknown): OpencodeContinueBinding => {
  const obj =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  const contextId =
    typeof obj.contextId === "string"
      ? obj.contextId
      : typeof obj.context_id === "string"
        ? obj.context_id
        : "";
  const metadata =
    obj.metadata && typeof obj.metadata === "object"
      ? (obj.metadata as Record<string, unknown>)
      : {};
  const trimmed = contextId.trim();
  return { contextId: trimmed ? trimmed : null, metadata, raw: value };
};

export const continueOpencodeSession = async (
  agentId: string,
  sessionId: string,
  options?: { source?: AgentSource },
): Promise<OpencodeContinueBinding> => {
  const scope = scopeForSource(options?.source ?? "personal");
  const response = await apiRequest<A2AExtensionResponse>(
    `${scope}/${encodeURIComponent(agentId)}/extensions/opencode/sessions/${encodeURIComponent(sessionId)}:continue`,
    {
      method: "POST",
    },
  );
  assertExtensionSuccess(response);
  return parseContinueBinding(response.result);
};

export const listOpencodeSessionsPage = async (
  agentId: string,
  options?: {
    page?: number;
    size?: number;
    query?: Record<string, unknown> | null;
    source?: AgentSource;
  },
): Promise<OpencodePaginatedResult> => {
  const scope = scopeForSource(options?.source ?? "personal");
  const response = await apiRequest<
    A2AExtensionResponse,
    A2AExtensionQueryRequest
  >(
    `${scope}/${encodeURIComponent(agentId)}/extensions/opencode/sessions:query`,
    {
      method: "POST",
      body: {
        page: options?.page ?? 1,
        size: options?.size ?? 20,
        query: options?.query ?? null,
      },
    },
  );

  assertExtensionSuccess(response);
  const envelope = normalizeEnvelope(response.result);
  const items = extractItems(envelope);
  const listEnvelope = {
    items,
    pagination: envelope.pagination,
    meta: envelope.meta,
  };
  const parsed = parsePaginatedListResponse(listEnvelope);
  const page = options?.page ?? 1;
  const size = options?.size ?? 20;
  const nextPage =
    typeof parsed.nextPage === "number"
      ? parsed.nextPage
      : items.length >= size
        ? page + 1
        : undefined;
  return { ...parsed, nextPage, envelope, raw: envelope.raw };
};

export const listOpencodeSessionMessagesPage = async (
  agentId: string,
  sessionId: string,
  options?: {
    page?: number;
    size?: number;
    query?: Record<string, unknown> | null;
    source?: AgentSource;
  },
): Promise<OpencodePaginatedResult> => {
  const scope = scopeForSource(options?.source ?? "personal");
  const response = await apiRequest<
    A2AExtensionResponse,
    A2AExtensionQueryRequest
  >(
    `${scope}/${encodeURIComponent(agentId)}/extensions/opencode/sessions/${encodeURIComponent(sessionId)}/messages:query`,
    {
      method: "POST",
      body: {
        page: options?.page ?? 1,
        size: options?.size ?? 50,
        query: options?.query ?? null,
      },
    },
  );

  assertExtensionSuccess(response);
  const envelope = normalizeEnvelope(response.result);
  const items = extractItems(envelope);
  const listEnvelope = {
    items,
    pagination: envelope.pagination,
    meta: envelope.meta,
  };
  const parsed = parsePaginatedListResponse(listEnvelope);
  const page = options?.page ?? 1;
  const size = options?.size ?? 50;
  const nextPage =
    typeof parsed.nextPage === "number"
      ? parsed.nextPage
      : items.length >= size
        ? page + 1
        : undefined;
  return { ...parsed, nextPage, envelope, raw: envelope.raw };
};

export type OpencodeSessionDirectoryItem = {
  agent_id: string;
  agent_source: AgentSource;
  agent_name: string;
  session_id: string;
  title: string;
  last_active_at?: string | null;
};

export const listOpencodeSessionsDirectoryPage = async (options?: {
  page?: number;
  size?: number;
  refresh?: boolean;
}): Promise<PaginatedResult<OpencodeSessionDirectoryItem>> => {
  const page = options?.page ?? 1;
  const size = options?.size ?? 50;
  const response = await apiRequest<
    {
      items: OpencodeSessionDirectoryItem[];
      pagination?: unknown;
      meta?: unknown;
    },
    { page: number; size: number; refresh: boolean }
  >("/me/a2a/opencode/sessions:query", {
    method: "POST",
    body: { page, size, refresh: options?.refresh ?? false },
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
