import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  createShortcut,
  deleteShortcut,
  listShortcuts,
  type ShortcutItem as ServerShortcutItem,
} from "@/lib/api/shortcuts";
import { createPersistStorage } from "@/lib/storage/mmkv";

type Shortcut = {
  id: string;
  title: string;
  prompt: string;
  isDefault: boolean;
  order: number;
};

const DEFAULT_SHORTCUTS: Shortcut[] = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    title: "📝 Summarize",
    prompt: "Please summarize our conversation so far.",
    isDefault: true,
    order: 0,
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    title: "🔍 Explain",
    prompt: "Can you explain this in more detail?",
    isDefault: true,
    order: 1,
  },
  {
    id: "33333333-3333-3333-3333-333333333333",
    title: "💡 Next Steps",
    prompt: "What should be our next steps?",
    isDefault: true,
    order: 2,
  },
  {
    id: "44444444-4444-4444-4444-444444444444",
    title: "✨ Polish",
    prompt: "Please polish the text I just sent.",
    isDefault: true,
    order: 3,
  },
  {
    id: "55555555-5555-5555-5555-555555555555",
    title: "❓ Help",
    prompt: "What are your main capabilities?",
    isDefault: true,
    order: 4,
  },
];

type ShortcutState = {
  shortcuts: Shortcut[];
  isSyncing: boolean;
  syncError: string | null;
  syncShortcuts: () => Promise<void>;
  addShortcut: (title: string, prompt: string) => Promise<void>;
  removeShortcut: (id: string) => Promise<void>;
  clearAll: () => void;
};

type LegacyShortcut = {
  id: string;
  label?: string;
  value?: string;
  isCustom?: boolean;
};

type PersistedShortcutState = {
  shortcuts: (Shortcut | LegacyShortcut)[];
  isSyncing?: boolean;
  syncError?: string | null;
};

const normalizeString = (value: unknown): string | null => {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
};

const normalizeOrder = (value: unknown, fallback: number): number => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value >= 0 ? value : fallback;
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value.trim(), 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  }
  return fallback;
};

const normalizeFromPersisted = (
  value: unknown,
  index: number,
  fallbackIdPrefix: string,
): Shortcut | null => {
  if (!value || typeof value !== "object") return null;
  const source = value as Record<string, unknown>;

  const id = normalizeString(source.id) ?? `${fallbackIdPrefix}${index + 1}`;
  const title =
    normalizeString(source.title) ??
    normalizeString(source.label) ??
    (typeof source.name === "string" ? source.name : null);
  const prompt =
    normalizeString(source.prompt) ??
    normalizeString(source.value) ??
    (typeof source.text === "string" ? source.text : null);
  if (!title || !prompt) return null;

  const isDefault =
    typeof source.isDefault === "boolean"
      ? source.isDefault
      : typeof source.is_default === "boolean"
        ? source.is_default
        : typeof source.isCustom === "boolean"
          ? !source.isCustom
          : false;

  return {
    id,
    title,
    prompt,
    isDefault,
    order: normalizeOrder(
      source.sort_order,
      normalizeOrder(source.order, index),
    ),
  };
};

const normalizePersistedShortcuts = (raw: unknown): Shortcut[] => {
  const fallback = [...DEFAULT_SHORTCUTS];
  if (
    !raw ||
    typeof raw !== "object" ||
    !Array.isArray((raw as PersistedShortcutState).shortcuts)
  ) {
    return fallback;
  }

  const parsedItems = (raw as PersistedShortcutState).shortcuts
    .map((item, index) =>
      normalizeFromPersisted(item, index, "local-shortcut-"),
    )
    .filter((item): item is Shortcut => item !== null);

  if (!parsedItems.length) {
    return fallback;
  }

  const hasDefault = parsedItems.some((item) => item.isDefault);
  const normalizedCustoms = parsedItems.filter((item) => !item.isDefault);
  const normalizedDefaults = hasDefault
    ? parsedItems
        .filter((item) => item.isDefault)
        .map((item) => ({
          ...item,
          isDefault: true,
        }))
    : [...DEFAULT_SHORTCUTS];

  const merged = [...normalizedDefaults, ...normalizedCustoms];
  const seen = new Set<string>();
  const deduped: Shortcut[] = [];
  for (const item of merged) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    deduped.push(item);
  }
  deduped.sort((left, right) => {
    if (left.order !== right.order) return left.order - right.order;
    return left.title.localeCompare(right.title);
  });
  return deduped;
};

const toShortcutFromServer = (item: ServerShortcutItem): Shortcut => ({
  id: item.id,
  title: item.title,
  prompt: item.prompt,
  isDefault: item.is_default,
  order: item.order,
});

const extractErrorMessage = (error: unknown): string | null => {
  if (error instanceof Error) {
    return error.message;
  }
  return null;
};

export const useShortcutStore = create<ShortcutState>()(
  persist(
    (set, get) => ({
      shortcuts: DEFAULT_SHORTCUTS,
      isSyncing: false,
      syncError: null,

      syncShortcuts: async () => {
        if (get().isSyncing) {
          return;
        }
        set({ isSyncing: true, syncError: null });
        try {
          const serverShortcuts = await listShortcuts();
          set({
            shortcuts: serverShortcuts.map(toShortcutFromServer),
            syncError: null,
          });
        } catch (error) {
          set({
            syncError: extractErrorMessage(error) ?? "Unable to sync shortcuts",
          });
        } finally {
          set({ isSyncing: false });
        }
      },

      addShortcut: async (title, prompt) => {
        const result = await createShortcut({
          title,
          prompt,
        });
        const next = toShortcutFromServer(result);
        set((state) => ({
          shortcuts: [
            ...state.shortcuts.filter((item) => item.id !== next.id),
            next,
          ],
        }));
      },

      removeShortcut: async (id) => {
        const existing = get().shortcuts.find((item) => item.id === id);
        if (!existing) return;
        if (existing.isDefault) {
          throw new Error("Cannot remove default shortcut");
        }
        await deleteShortcut(id);
        set((state) => ({
          shortcuts: state.shortcuts.filter((item) => item.id !== id),
        }));
      },

      clearAll: () => set({ shortcuts: [...DEFAULT_SHORTCUTS] }),
    }),
    {
      name: "a2a-client-hub.shortcuts",
      storage: createPersistStorage(),
      version: 2,
      migrate: (state) => {
        const migrated = normalizePersistedShortcuts(state);
        return {
          shortcuts: migrated,
          isSyncing: false,
          syncError: null,
        };
      },
    },
  ),
);

export type { Shortcut };
