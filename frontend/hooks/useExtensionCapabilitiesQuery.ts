import { useQuery } from "@tanstack/react-query";

import { getExtensionCapabilities } from "@/lib/api/a2aExtensions";
import { queryKeys } from "@/lib/queryKeys";
import { type AgentSource } from "@/store/agents";

export type GenericCapabilityStatus = "unknown" | "supported" | "unsupported";

export const useExtensionCapabilitiesQuery = ({
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
        ? queryKeys.agents.extensionCapabilities({
            agentId: resolvedAgentId,
            source: resolvedSource,
          })
        : (["agents", "extension-capabilities", "idle"] as const),
    queryFn: async () =>
      await getExtensionCapabilities({
        source: resolvedSource as AgentSource,
        agentId: resolvedAgentId as string,
      }),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const modelSelectionStatus: GenericCapabilityStatus =
    query.data?.modelSelection === true
      ? "supported"
      : query.data?.modelSelection === false
        ? "unsupported"
        : "unknown";

  return {
    ...query,
    runtimeStatusContract: query.data?.runtimeStatus ?? null,
    modelSelectionStatus,
    canShowModelPicker: modelSelectionStatus !== "unsupported",
  };
};
