import { useCallback, useState } from "react";

import { toast } from "@/lib/toast";

type RunMode = "loading" | "refreshing";

type RunOptions = {
  mode?: RunMode;
  errorTitle: string;
  fallbackMessage: string;
  mapErrorMessage?: (error: unknown) => string | null | undefined;
};

export function useAsyncListLoad() {
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const run = useCallback(
    async <T>(task: () => Promise<T>, options: RunOptions) => {
      const mode = options.mode ?? "loading";
      if (mode === "refreshing") {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      try {
        return await task();
      } catch (error) {
        const mapped = options.mapErrorMessage?.(error);
        const message =
          typeof mapped === "string" && mapped.trim()
            ? mapped
            : error instanceof Error
              ? error.message
              : options.fallbackMessage;
        toast.error(options.errorTitle, message);
        return null;
      } finally {
        if (mode === "refreshing") {
          setRefreshing(false);
        } else {
          setLoading(false);
        }
      }
    },
    [],
  );

  return {
    loading,
    refreshing,
    run,
  };
}
