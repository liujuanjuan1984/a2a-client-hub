import { type ItemsEnvelope, parseListResponse } from "@/lib/api/listParser";

export type ListEnvelope<T> = ItemsEnvelope<T> & {
  pagination?: unknown;
  meta?: unknown;
};

export type ListResponse<T> = T[] | ListEnvelope<T>;

export type PaginatedResult<T> = {
  items: T[];
  pagination: unknown;
  meta: unknown;
  nextPage?: number;
  currentPage?: number;
};

type NextPageFallbackOptions<T> = {
  parsed: PaginatedResult<T>;
  page: number;
  size: number;
};

export const inferNextPage = (
  pagination: unknown,
): { nextPage?: number; currentPage?: number } => {
  if (!pagination || typeof pagination !== "object") {
    return {};
  }
  const typed = pagination as Record<string, unknown>;
  const page = typeof typed.page === "number" ? typed.page : undefined;
  const next =
    typeof typed.next_page === "number" ? typed.next_page : undefined;
  const hasNext =
    typeof typed.has_next === "boolean" ? typed.has_next : undefined;
  const totalPages =
    typeof typed.total_pages === "number" ? typed.total_pages : undefined;
  const size = typeof typed.size === "number" ? typed.size : undefined;
  const totalItems =
    typeof typed.total_items === "number" ? typed.total_items : undefined;

  if (hasNext === true && typeof next === "number") {
    return { nextPage: next, currentPage: page };
  }
  if (typeof page === "number" && typeof totalPages === "number") {
    return page < totalPages ? { nextPage: page + 1, currentPage: page } : {};
  }
  if (
    typeof page === "number" &&
    typeof size === "number" &&
    typeof totalItems === "number"
  ) {
    return page * size < totalItems
      ? { nextPage: page + 1, currentPage: page }
      : {};
  }
  return { currentPage: page };
};

export const parsePaginatedListResponse = <T>(
  response: ListResponse<T>,
): PaginatedResult<T> => {
  const parsed = parseListResponse(response);
  const envelope = parsed.envelope as {
    pagination?: unknown;
    meta?: unknown;
  } | null;
  const pagination = envelope?.pagination;
  const meta = envelope?.meta;
  const { nextPage, currentPage } = inferNextPage(pagination);

  return {
    items: parsed.items,
    pagination,
    meta,
    nextPage,
    currentPage,
  };
};

export const resolveNextPageWithFallback = <T>({
  parsed,
  page,
  size,
}: NextPageFallbackOptions<T>): number | undefined => {
  if (typeof parsed.nextPage === "number") {
    return parsed.nextPage;
  }

  if (parsed.pagination && typeof parsed.pagination === "object") {
    const typedPagination = parsed.pagination as Record<string, unknown>;
    const pages =
      typeof typedPagination.pages === "number" ? typedPagination.pages : null;
    if (typeof pages === "number" && page < pages) {
      return page + 1;
    }
  }

  return parsed.items.length >= size ? page + 1 : undefined;
};
