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

export const listOpencodeSessionsPage = async (
  agentId: string,
  options?: {
    page?: number;
    size?: number;
    query?: Record<string, unknown> | null;
  },
): Promise<OpencodePaginatedResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    A2AExtensionQueryRequest
  >(
    `/me/a2a/agents/${encodeURIComponent(agentId)}/extensions/opencode/sessions:query`,
    {
      method: "POST",
      body: {
        page: options?.page ?? 1,
        size: options?.size ?? null,
        query: options?.query ?? null,
      },
    },
  );

  assertExtensionSuccess(response);
  const envelope = normalizeEnvelope(response.result);
  const listEnvelope = {
    items: Array.isArray(envelope.items) ? envelope.items : [],
    pagination: envelope.pagination,
    meta: envelope.meta,
  };
  const parsed = parsePaginatedListResponse(listEnvelope);
  return { ...parsed, envelope, raw: envelope.raw };
};

export const listOpencodeSessionMessagesPage = async (
  agentId: string,
  sessionId: string,
  options?: {
    page?: number;
    size?: number;
    query?: Record<string, unknown> | null;
  },
): Promise<OpencodePaginatedResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    A2AExtensionQueryRequest
  >(
    `/me/a2a/agents/${encodeURIComponent(agentId)}/extensions/opencode/sessions/${encodeURIComponent(sessionId)}/messages:query`,
    {
      method: "POST",
      body: {
        page: options?.page ?? 1,
        size: options?.size ?? null,
        query: options?.query ?? null,
      },
    },
  );

  assertExtensionSuccess(response);
  const envelope = normalizeEnvelope(response.result);
  const listEnvelope = {
    items: Array.isArray(envelope.items) ? envelope.items : [],
    pagination: envelope.pagination,
    meta: envelope.meta,
  };
  const parsed = parsePaginatedListResponse(listEnvelope);
  return { ...parsed, envelope, raw: envelope.raw };
};
