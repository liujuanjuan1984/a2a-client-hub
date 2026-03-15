import { useMemo } from "react";

import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { useAgentStore } from "@/store/agents";

export function useAgentSelection(routeAgentId?: string | null) {
  const storeActiveAgentId = useAgentStore((state) => state.activeAgentId);
  const activeAgentId = routeAgentId || storeActiveAgentId;

  const { data: agents = [], isFetched: hasFetchedAgents } =
    useAgentsCatalogQuery(true);

  const agent = useMemo(
    () => agents.find((item) => item.id === activeAgentId),
    [agents, activeAgentId],
  );

  return { activeAgentId, agent, hasFetchedAgents };
}
