import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createShortcut,
  deleteShortcut,
  listShortcuts,
  updateShortcut,
  type ShortcutItem,
} from "@/lib/api/shortcuts";
import { queryKeys } from "@/lib/queryKeys";

type Shortcut = {
  id: string;
  title: string;
  prompt: string;
  isDefault: boolean;
  order: number;
  agentId: string | null;
  createdAt: string | null;
};

const DEFAULT_SHORTCUTS: Shortcut[] = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    title: "📝 Summarize",
    prompt: "Please summarize our conversation so far.",
    isDefault: true,
    order: 0,
    agentId: null,
    createdAt: null,
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    title: "🔍 Explain",
    prompt: "Can you explain this in more detail?",
    isDefault: true,
    order: 1,
    agentId: null,
    createdAt: null,
  },
  {
    id: "33333333-3333-3333-3333-333333333333",
    title: "💡 Next Steps",
    prompt: "What should be our next steps?",
    isDefault: true,
    order: 2,
    agentId: null,
    createdAt: null,
  },
  {
    id: "44444444-4444-4444-4444-444444444444",
    title: "✨ Polish",
    prompt: "Please polish the text I just sent.",
    isDefault: true,
    order: 3,
    agentId: null,
    createdAt: null,
  },
  {
    id: "55555555-5555-5555-5555-555555555555",
    title: "❓ Help",
    prompt: "What are your main capabilities?",
    isDefault: true,
    order: 4,
    agentId: null,
    createdAt: null,
  },
];

const toShortcut = (item: ShortcutItem): Shortcut => ({
  id: item.id,
  title: item.title,
  prompt: item.prompt,
  isDefault: item.is_default,
  order: item.order,
  agentId: item.agent_id,
  createdAt: item.created_at,
});

const sortDefaultShortcuts = (items: Shortcut[]) =>
  [...items].sort((left, right) => {
    if (left.order !== right.order) {
      return left.order - right.order;
    }
    return left.title.localeCompare(right.title);
  });

const sortCustomShortcutsByNewest = (items: Shortcut[]) =>
  [...items].sort((left, right) => {
    const leftCreatedAt = left.createdAt
      ? Date.parse(left.createdAt)
      : Number.NaN;
    const rightCreatedAt = right.createdAt
      ? Date.parse(right.createdAt)
      : Number.NaN;
    const leftHasCreatedAt = Number.isFinite(leftCreatedAt);
    const rightHasCreatedAt = Number.isFinite(rightCreatedAt);

    if (
      leftHasCreatedAt &&
      rightHasCreatedAt &&
      leftCreatedAt !== rightCreatedAt
    ) {
      return rightCreatedAt - leftCreatedAt;
    }
    if (leftHasCreatedAt !== rightHasCreatedAt) {
      return leftHasCreatedAt ? -1 : 1;
    }
    if (left.order !== right.order) {
      return right.order - left.order;
    }
    return left.title.localeCompare(right.title);
  });

const mergeDefaultShortcuts = (items: Shortcut[]) => {
  const merged = new Map<string, Shortcut>();
  DEFAULT_SHORTCUTS.forEach((item) => merged.set(item.id, item));
  items.forEach((item) => merged.set(item.id, item));
  return Array.from(merged.values());
};

export const useShortcutsQuery = () => {
  const query = useQuery({
    queryKey: queryKeys.shortcuts.list(),
    queryFn: async () => {
      const items = await listShortcuts();
      return mergeDefaultShortcuts(items.map(toShortcut));
    },
    staleTime: 60_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const shortcuts = query.data ?? DEFAULT_SHORTCUTS;
  const getShortcutsForAgent = (agentId: string | null) => {
    const defaultShortcuts = sortDefaultShortcuts(
      shortcuts.filter((item) => item.isDefault),
    );
    const customShortcuts = shortcuts.filter((item) => !item.isDefault);

    if (!agentId) {
      const generalCustomShortcuts = sortCustomShortcutsByNewest(
        customShortcuts.filter((item) => item.agentId === null),
      );
      return [...generalCustomShortcuts, ...defaultShortcuts];
    }
    const agentSpecificShortcuts = sortCustomShortcutsByNewest(
      customShortcuts.filter((item) => item.agentId === agentId),
    );
    const generalCustomShortcuts = sortCustomShortcutsByNewest(
      customShortcuts.filter((item) => item.agentId === null),
    );
    return [
      ...agentSpecificShortcuts,
      ...generalCustomShortcuts,
      ...defaultShortcuts,
    ];
  };

  return {
    ...query,
    shortcuts,
    getShortcutsForAgent,
  };
};

export const useCreateShortcutMutation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      title: string;
      prompt: string;
      agentId?: string | null;
    }) => {
      return await createShortcut({
        title: payload.title,
        prompt: payload.prompt,
        agent_id: payload.agentId,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.shortcuts.list(),
      });
    },
  });
};

export const useUpdateShortcutMutation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      shortcutId: string;
      title: string;
      prompt: string;
      agentId?: string | null;
      clearAgent?: boolean;
    }) => {
      return await updateShortcut(payload.shortcutId, {
        title: payload.title,
        prompt: payload.prompt,
        agent_id: payload.agentId,
        clear_agent: payload.clearAgent,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.shortcuts.list(),
      });
    },
  });
};

export const useDeleteShortcutMutation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (shortcutId: string) => {
      await deleteShortcut(shortcutId);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.shortcuts.list(),
      });
    },
  });
};
