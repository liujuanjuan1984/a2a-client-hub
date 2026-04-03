import { useQuery } from "@tanstack/react-query";

import {
  listCodexApps,
  listCodexPlugins,
  listCodexSkills,
  readCodexPlugin,
  type CodexDiscoveryListKind,
} from "@/lib/api/a2aExtensions";
import { queryKeys } from "@/lib/queryKeys";
import { type AgentSource } from "@/store/agents";

export const useCodexDiscoveryListQuery = ({
  agentId,
  source,
  kind,
  enabled = true,
}: {
  agentId?: string | null;
  source?: AgentSource | null;
  kind: CodexDiscoveryListKind;
  enabled?: boolean;
}) => {
  const resolvedAgentId = agentId?.trim() || null;
  const resolvedSource = source ?? null;

  return useQuery({
    enabled: enabled && Boolean(resolvedAgentId && resolvedSource),
    queryKey:
      resolvedAgentId && resolvedSource
        ? queryKeys.agents.codexDiscoveryList({
            agentId: resolvedAgentId,
            source: resolvedSource,
            kind,
          })
        : (["agents", "codex-discovery", "list", "idle", kind] as const),
    queryFn: async () => {
      const input = {
        source: resolvedSource as AgentSource,
        agentId: resolvedAgentId as string,
      };
      if (kind === "skills") {
        return await listCodexSkills(input);
      }
      if (kind === "apps") {
        return await listCodexApps(input);
      }
      return await listCodexPlugins(input);
    },
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
};

export const useCodexPluginReadQuery = ({
  agentId,
  source,
  marketplacePath,
  pluginName,
  enabled = true,
}: {
  agentId?: string | null;
  source?: AgentSource | null;
  marketplacePath?: string | null;
  pluginName?: string | null;
  enabled?: boolean;
}) => {
  const resolvedAgentId = agentId?.trim() || null;
  const resolvedSource = source ?? null;
  const resolvedMarketplacePath = marketplacePath?.trim() || null;
  const resolvedPluginName = pluginName?.trim() || null;

  return useQuery({
    enabled:
      enabled &&
      Boolean(
        resolvedAgentId &&
        resolvedSource &&
        resolvedMarketplacePath &&
        resolvedPluginName,
      ),
    queryKey:
      resolvedAgentId &&
      resolvedSource &&
      resolvedMarketplacePath &&
      resolvedPluginName
        ? queryKeys.agents.codexDiscoveryPlugin({
            agentId: resolvedAgentId,
            source: resolvedSource,
            marketplacePath: resolvedMarketplacePath,
            pluginName: resolvedPluginName,
          })
        : (["agents", "codex-discovery", "plugin", "idle"] as const),
    queryFn: async () =>
      await readCodexPlugin({
        source: resolvedSource as AgentSource,
        agentId: resolvedAgentId as string,
        marketplacePath: resolvedMarketplacePath as string,
        pluginName: resolvedPluginName as string,
      }),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
};
