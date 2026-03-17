import { useQuery } from "@tanstack/react-query";

import { getOpencodeDiscoveryCapability } from "@/lib/api/a2aExtensions";
import { queryKeys } from "@/lib/queryKeys";
import { type AgentSource } from "@/store/agents";

export type OpencodeCapabilityStatus = "unknown" | "supported" | "unsupported";

export const useOpencodeCapabilityQuery = ({
  agentId,
  source,
  enabled = true,
}: {
  agentId?: string | null;
  source?: AgentSource | null;
  enabled?: boolean;
}) => {
  const resolvedAgentId = agentId?.trim() || null;
  const resolvedSource = source ?? null;

  const query = useQuery({
    enabled: enabled && Boolean(resolvedAgentId && resolvedSource),
    queryKey:
      resolvedAgentId && resolvedSource
        ? queryKeys.agents.opencodeCapability({
            agentId: resolvedAgentId,
            source: resolvedSource,
          })
        : (["agents", "opencode-capability", "idle"] as const),
    queryFn: async () =>
      await getOpencodeDiscoveryCapability({
        source: resolvedSource as AgentSource,
        agentId: resolvedAgentId as string,
      }),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const capabilityStatus: OpencodeCapabilityStatus =
    query.data?.supported === true
      ? "supported"
      : query.data?.supported === false
        ? "unsupported"
        : "unknown";

  return {
    ...query,
    capabilityStatus,
    canShowModelPicker: capabilityStatus !== "unsupported",
  };
};
