import { apiRequest } from "@/lib/api/client";
import { parsePaginatedListResponse } from "@/lib/api/pagination";
import { type SessionMessageItem } from "@/lib/sessionHistory";

type SessionMessageListResponse =
  | SessionMessageItem[]
  | {
      items: SessionMessageItem[];
      pagination?: unknown;
      meta?: unknown;
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
