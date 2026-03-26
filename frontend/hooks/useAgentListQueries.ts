import { useQuery } from "@tanstack/react-query";

import { listAgents } from "@/lib/api/a2aAgents";
import { listHubAgents } from "@/lib/api/hubA2aAgentsUser";
import { queryKeys } from "@/lib/queryKeys";

export function usePersonalAgentsListQuery(input: {
  page: number;
  size: number;
  healthBucket: "all" | "healthy" | "attention";
  enabled?: boolean;
}) {
  const { page, size, healthBucket, enabled = true } = input;

  return useQuery({
    queryKey: queryKeys.agents.list({ page, size, healthBucket }),
    queryFn: () => listAgents(page, size, healthBucket),
    enabled,
  });
}

export function useSharedAgentsListQuery(input: {
  page: number;
  size: number;
  enabled?: boolean;
}) {
  const { page, size, enabled = true } = input;

  return useQuery({
    queryKey: queryKeys.agents.sharedList({ page, size }),
    queryFn: () => listHubAgents(page, size),
    enabled,
  });
}
