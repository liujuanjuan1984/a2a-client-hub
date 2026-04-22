import { useQuery } from "@tanstack/react-query";

import { getSessionUpstreamTask } from "@/lib/api/sessions";
import { queryKeys } from "@/lib/queryKeys";

export function useSessionUpstreamTaskQuery(options: {
  conversationId?: string | null;
  taskId?: string | null;
  historyLength?: number | null;
  enabled?: boolean;
}) {
  const conversationId = options.conversationId?.trim() || null;
  const taskId = options.taskId?.trim() || null;
  const historyLength =
    typeof options.historyLength === "number" &&
    Number.isFinite(options.historyLength) &&
    options.historyLength >= 0
      ? Math.floor(options.historyLength)
      : null;

  return useQuery({
    enabled: options.enabled !== false && Boolean(conversationId && taskId),
    queryKey:
      conversationId && taskId
        ? [
            ...queryKeys.sessions.upstreamTask(conversationId, taskId),
            historyLength,
          ]
        : (["sessions", "upstream-task", "idle"] as const),
    queryFn: async () =>
      await getSessionUpstreamTask(conversationId as string, taskId as string, {
        historyLength,
      }),
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: true,
    refetchInterval: false,
  });
}
