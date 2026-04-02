import { useCallback, useMemo } from "react";

import { type PaginatedPage, usePaginatedList } from "@/hooks/usePaginatedList";
import {
  listAgentsPage,
  type A2AAgentHealthBucket,
  type A2AAgentListResponse,
  type A2AAgentResponse,
} from "@/lib/api/a2aAgents";
import {
  listHubAgentsPage,
  type HubA2AAgentUserResponse,
} from "@/lib/api/hubA2aAgentsUser";
import { queryKeys } from "@/lib/queryKeys";

const DEFAULT_PERSONAL_PAGE_SIZE = 12;
const DEFAULT_SHARED_PAGE_SIZE = 8;

type PersonalAgentsPage = PaginatedPage<
  A2AAgentResponse,
  {
    pagination: A2AAgentListResponse["pagination"];
    meta: A2AAgentListResponse["meta"];
  }
>;

export function usePersonalAgentsListQuery(input: {
  size: number;
  healthBucket: A2AAgentHealthBucket;
  enabled?: boolean;
}) {
  const size =
    typeof input.size === "number" && Number.isFinite(input.size) && input.size
      ? Math.max(1, Math.floor(input.size))
      : DEFAULT_PERSONAL_PAGE_SIZE;
  const queryKey = useMemo(
    () => queryKeys.agents.list({ size, healthBucket: input.healthBucket }),
    [input.healthBucket, size],
  );

  const fetchPage = useCallback(
    async (page: number): Promise<PersonalAgentsPage> => {
      const result = await listAgentsPage({
        page,
        size,
        healthBucket: input.healthBucket,
      });

      return {
        items: result.items,
        nextPage: result.nextPage,
        pagination: result.pagination,
        meta: result.meta,
      };
    },
    [input.healthBucket, size],
  );

  const query = usePaginatedList<
    A2AAgentResponse,
    {
      pagination: A2AAgentListResponse["pagination"];
      meta: A2AAgentListResponse["meta"];
    }
  >({
    queryKey,
    fetchPage,
    getKey: (item) => item.id,
    errorTitle: "Load agents failed",
    fallbackMessage: "Could not load agents from server.",
    enabled: input.enabled ?? true,
  });

  const counts = query.pages[0]?.meta?.counts;
  const refresh = useCallback(async () => {
    await query.loadFirstPage("refreshing");
  }, [query.loadFirstPage]);

  return {
    ...query,
    counts,
    refresh,
  };
}

export function useSharedAgentsListQuery(input: {
  size: number;
  enabled?: boolean;
}) {
  const size =
    typeof input.size === "number" && Number.isFinite(input.size) && input.size
      ? Math.max(1, Math.floor(input.size))
      : DEFAULT_SHARED_PAGE_SIZE;
  const queryKey = useMemo(() => queryKeys.agents.sharedList({ size }), [size]);

  const fetchPage = useCallback(
    async (page: number) => {
      const result = await listHubAgentsPage({ page, size });
      return { items: result.items, nextPage: result.nextPage };
    },
    [size],
  );

  const query = usePaginatedList<HubA2AAgentUserResponse>({
    queryKey,
    fetchPage,
    getKey: (item) => item.id,
    errorTitle: "Load shared agents failed",
    fallbackMessage: "Could not load shared agents from server.",
    enabled: input.enabled ?? true,
  });

  const refresh = useCallback(async () => {
    await query.loadFirstPage("refreshing");
  }, [query.loadFirstPage]);

  return {
    ...query,
    refresh,
  };
}
