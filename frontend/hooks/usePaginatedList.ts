import { useCallback, useMemo, useState } from "react";

import { useAsyncListLoad } from "@/hooks/useAsyncListLoad";
import { ApiRequestError } from "@/lib/api/client";
import { toast } from "@/lib/toast";

type LoadMode = "loading" | "refreshing";

export type PaginatedPage<T> = {
  items: T[];
  nextPage?: number;
};

type Options<T> = {
  fetchPage: (page: number) => Promise<PaginatedPage<T>>;
  getKey: (item: T) => string;
  errorTitle: string;
  fallbackMessage: string;
  mapErrorMessage?: (error: unknown) => string | null | undefined;
};

const mergeUniqueByKey = <T>(
  prev: T[],
  next: T[],
  getKey: (item: T) => string,
) => {
  const map = new Map<string, T>();
  prev.forEach((item) => map.set(getKey(item), item));
  next.forEach((item) => map.set(getKey(item), item));
  return Array.from(map.values());
};

export function usePaginatedList<T>({
  fetchPage,
  getKey,
  errorTitle,
  fallbackMessage,
  mapErrorMessage,
}: Options<T>) {
  const { loading, refreshing, run } = useAsyncListLoad();
  const [items, setItems] = useState<T[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const hasMore = useMemo(() => typeof nextPage === "number", [nextPage]);

  const loadFirstPage = useCallback(
    async (mode: LoadMode = "loading") => {
      await run(
        async () => {
          const result = await fetchPage(1);
          setItems(result.items);
          setNextPage(
            typeof result.nextPage === "number" ? result.nextPage : null,
          );
        },
        { mode, errorTitle, fallbackMessage, mapErrorMessage },
      );
    },
    [run, fetchPage, errorTitle, fallbackMessage, mapErrorMessage],
  );

  const reset = useCallback(() => {
    setItems([]);
    setNextPage(null);
    setLoadingMore(false);
  }, []);

  const loadMore = useCallback(async () => {
    if (!hasMore) return;
    if (loadingMore) return;

    const page = nextPage as number;
    setLoadingMore(true);
    try {
      const result = await fetchPage(page);
      setItems((prev) => mergeUniqueByKey(prev, result.items, getKey));
      setNextPage(typeof result.nextPage === "number" ? result.nextPage : null);
    } catch (error) {
      const mapped = mapErrorMessage?.(error);
      const message =
        typeof mapped === "string" && mapped.trim()
          ? mapped
          : error instanceof ApiRequestError
            ? error.message
            : error instanceof Error
              ? error.message
              : fallbackMessage;
      toast.error(errorTitle, message);
    } finally {
      setLoadingMore(false);
    }
  }, [
    errorTitle,
    fallbackMessage,
    fetchPage,
    getKey,
    hasMore,
    loadingMore,
    mapErrorMessage,
    nextPage,
  ]);

  return {
    items,
    setItems,
    nextPage,
    hasMore,
    loading,
    refreshing,
    loadingMore,
    reset,
    loadFirstPage,
    loadMore,
  };
}
