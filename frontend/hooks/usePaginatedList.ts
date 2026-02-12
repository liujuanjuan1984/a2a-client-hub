import {
  useInfiniteQuery,
  useQueryClient,
  type InfiniteData,
  type QueryKey,
} from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiRequestError } from "@/lib/api/client";
import { toast } from "@/lib/toast";

type LoadMode = "loading" | "refreshing";

type PaginatedPage<T> = {
  items: T[];
  nextPage?: number;
};

type Options<T> = {
  queryKey: QueryKey;
  fetchPage: (page: number) => Promise<PaginatedPage<T>>;
  getKey: (item: T) => string;
  errorTitle: string;
  fallbackMessage: string;
  mapErrorMessage?: (error: unknown) => string | null | undefined;
  enabled?: boolean;
};

const mergeUniqueByKey = <T>(
  pages: PaginatedPage<T>[],
  getKey: (item: T) => string,
) => {
  const map = new Map<string, T>();
  pages.forEach((page) => {
    page.items.forEach((item) => {
      map.set(getKey(item), item);
    });
  });
  return Array.from(map.values());
};

const resolveErrorMessage = (
  error: unknown,
  fallbackMessage: string,
  mapErrorMessage?: (error: unknown) => string | null | undefined,
) => {
  const mapped = mapErrorMessage?.(error);
  if (typeof mapped === "string" && mapped.trim()) {
    return mapped;
  }
  if (error instanceof ApiRequestError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallbackMessage;
};

export function usePaginatedList<T>({
  queryKey,
  fetchPage,
  getKey,
  errorTitle,
  fallbackMessage,
  mapErrorMessage,
  enabled = true,
}: Options<T>) {
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const lastErrorSignatureRef = useRef<string | null>(null);

  const query = useInfiniteQuery({
    queryKey,
    enabled,
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const page =
        typeof pageParam === "number" && Number.isFinite(pageParam)
          ? pageParam
          : 1;
      return await fetchPage(page);
    },
    getNextPageParam: (lastPage) => {
      return typeof lastPage.nextPage === "number"
        ? lastPage.nextPage
        : undefined;
    },
  });

  const pages = query.data?.pages ?? [];

  const items = useMemo(() => mergeUniqueByKey(pages, getKey), [pages, getKey]);

  const nextPage = useMemo(() => {
    if (pages.length === 0) return null;
    const lastPage = pages[pages.length - 1];
    return typeof lastPage?.nextPage === "number" ? lastPage.nextPage : null;
  }, [pages]);

  const hasMore = useMemo(() => typeof nextPage === "number", [nextPage]);

  const showErrorToast = useCallback(
    (error: unknown) => {
      const message = resolveErrorMessage(
        error,
        fallbackMessage,
        mapErrorMessage,
      );
      const signature = `${errorTitle}:${message}`;
      if (lastErrorSignatureRef.current === signature) return;
      lastErrorSignatureRef.current = signature;
      toast.error(errorTitle, message);
    },
    [errorTitle, fallbackMessage, mapErrorMessage],
  );

  useEffect(() => {
    if (!query.isError || !query.error) {
      lastErrorSignatureRef.current = null;
      return;
    }
    showErrorToast(query.error);
  }, [query.error, query.isError, showErrorToast]);

  const keepFirstPageOnly = useCallback(() => {
    queryClient.setQueryData<
      InfiniteData<PaginatedPage<T>, number> | undefined
    >(queryKey, (current) => {
      if (!current || current.pages.length <= 1) {
        return current;
      }
      return {
        pages: [current.pages[0]],
        pageParams: [current.pageParams[0] ?? 1],
      };
    });
  }, [queryClient, queryKey]);

  const restoreSnapshot = useCallback(
    (snapshot: InfiniteData<PaginatedPage<T>, number> | undefined) => {
      if (!snapshot) return;
      queryClient.setQueryData(queryKey, snapshot);
    },
    [queryClient, queryKey],
  );

  const loadFirstPage = useCallback(
    async (mode: LoadMode = "loading") => {
      const snapshot =
        mode === "refreshing"
          ? queryClient.getQueryData<InfiniteData<PaginatedPage<T>, number>>(
              queryKey,
            )
          : undefined;

      if (mode === "refreshing") {
        setRefreshing(true);
        keepFirstPageOnly();
      }

      try {
        const result = await query.refetch();
        if (result.status === "error") {
          restoreSnapshot(snapshot);
          showErrorToast(result.error);
          return false;
        }
        return true;
      } catch (error) {
        restoreSnapshot(snapshot);
        showErrorToast(error);
        return false;
      } finally {
        if (mode === "refreshing") {
          setRefreshing(false);
        }
      }
    },
    [
      keepFirstPageOnly,
      query,
      queryClient,
      queryKey,
      restoreSnapshot,
      showErrorToast,
    ],
  );

  const reset = useCallback(() => {
    lastErrorSignatureRef.current = null;
    queryClient.removeQueries({ queryKey, exact: true });
  }, [queryClient, queryKey]);

  const loadMore = useCallback(async () => {
    if (!hasMore || query.isFetchingNextPage) return;
    try {
      await query.fetchNextPage();
    } catch (error) {
      showErrorToast(error);
    }
  }, [hasMore, query, showErrorToast]);

  const setItems = useCallback(
    (nextItems: T[]) => {
      const data: InfiniteData<PaginatedPage<T>, number> = {
        pages: [{ items: nextItems, nextPage: undefined }],
        pageParams: [1],
      };
      queryClient.setQueryData(queryKey, data);
    },
    [queryClient, queryKey],
  );

  const loading = query.status === "pending" && pages.length === 0;

  return {
    error: query.error,
    isError: query.isError,
    items,
    setItems,
    nextPage,
    hasMore,
    loading,
    refreshing:
      refreshing || (query.isFetching && !query.isFetchingNextPage && !loading),
    loadingMore: query.isFetchingNextPage,
    reset,
    loadFirstPage,
    loadMore,
  };
}
