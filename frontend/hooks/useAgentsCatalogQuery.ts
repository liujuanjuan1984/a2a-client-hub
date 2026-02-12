import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/lib/queryKeys";
import { useAgentStore } from "@/store/agents";

export function useAgentsCatalogQuery(enabled: boolean) {
  const loadAgents = useAgentStore((state) => state.loadAgents);

  return useQuery({
    queryKey: queryKeys.agents.catalog(),
    enabled,
    queryFn: async () => {
      await loadAgents();
      return useAgentStore.getState().agents;
    },
  });
}
