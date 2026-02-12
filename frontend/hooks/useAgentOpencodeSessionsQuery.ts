import { useCallback } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { A2AExtensionCallError } from "@/lib/api/a2aExtensions";
import { ApiRequestError } from "@/lib/api/client";
import { listOpencodeSessionsPage } from "@/lib/api/opencodeSessions";
import { getOpencodeSessionId } from "@/lib/opencodeAdapters";
import { queryKeys } from "@/lib/queryKeys";

export function useAgentOpencodeSessionsQuery(options: {
  agentId: string;
  source: "personal" | "shared";
  enabled: boolean;
}) {
  const { agentId, source, enabled } = options;

  const fetchPage = useCallback(
    async (page: number) => {
      const result = await listOpencodeSessionsPage(agentId, {
        page,
        source,
      });
      return { items: result.items, nextPage: result.nextPage };
    },
    [agentId, source],
  );

  const mapErrorMessage = useCallback((error: unknown) => {
    if (error instanceof A2AExtensionCallError) {
      if (error.errorCode === "upstream_unreachable") {
        return "Upstream is unreachable.";
      }
      if (error.errorCode === "upstream_http_error") {
        return "Upstream returned an HTTP error.";
      }
      return error.errorCode
        ? `Extension error: ${error.errorCode}`
        : error.message;
    }
    if (error instanceof ApiRequestError && error.status === 502) {
      return "Extension is not supported or the contract is invalid.";
    }
    return null;
  }, []);

  return usePaginatedList<unknown>({
    queryKey: queryKeys.sessions.opencodeByAgent(agentId, source),
    fetchPage,
    getKey: (item) => getOpencodeSessionId(item),
    errorTitle: "Load OpenCode sessions failed",
    fallbackMessage: "Load failed.",
    mapErrorMessage,
    enabled,
  });
}
