import { apiRequest } from "@/lib/api/client";
import { parseListResponse } from "@/lib/api/listParser";
import { parsePaginatedListResponse } from "@/lib/api/pagination";
import { type SessionMessageItem } from "@/lib/sessionHistory";

export type SessionSource = "manual" | "scheduled";

export type SessionItem = {
  id: string;
  agent_id: string;
  title?: string | null;
  source: SessionSource;
  job_id?: string | null;
  run_id?: string | null;
  last_active_at?: string | null;
  created_at?: string | null;
};

type SessionListResponse =
  | SessionItem[]
  | {
      items: SessionItem[];
      pagination?: unknown;
      meta?: unknown;
    };

const DEFAULT_PAGE_SIZE = 50;

export const listSessionsPage = async (
  source?: SessionSource,
  options?: { page?: number; size?: number },
) => {
  const response = await apiRequest<SessionListResponse>("/me/sessions", {
    query: {
      page: options?.page ?? 1,
      size: options?.size ?? DEFAULT_PAGE_SIZE,
      source,
    },
  });

  const parsed = parsePaginatedListResponse(response);
  return parsed;
};

export const listSessions = async (source?: SessionSource) => {
  const { items } = await listSessionsPage(source);
  return items;
};

type SessionMessageListResponse =
  | SessionMessageItem[]
  | {
      items: SessionMessageItem[];
      pagination?: unknown;
      meta?: unknown;
    };

export const listSessionMessages = async (
  sessionId: string,
  options?: { page?: number; size?: number },
) => {
  const response = await apiRequest<SessionMessageListResponse>(
    `/me/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      query: {
        page: options?.page ?? 1,
        size: options?.size ?? 100,
      },
    },
  );

  return parseListResponse(response).items;
};

export const listSessionMessagesPage = async (
  sessionId: string,
  options?: { page?: number; size?: number },
) => {
  const page = options?.page ?? 1;
  const size = options?.size ?? 100;
  const response = await apiRequest<SessionMessageListResponse>(
    `/me/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      query: { page, size },
    },
  );

  const parsed = parsePaginatedListResponse(response);

  // Backward-compatible heuristic when the backend doesn't send pagination.
  const nextPage =
    typeof parsed.nextPage === "number"
      ? parsed.nextPage
      : parsed.items.length >= size
        ? page + 1
        : undefined;

  return { ...parsed, nextPage };
};
