import { create } from "zustand";
import { persist } from "zustand/middleware";

import { generateId } from "@/lib/id";
import { createPersistStorage } from "@/lib/storage/mmkv";

export type Shortcut = {
  id: string;
  label: string;
  value: string;
  isCustom: boolean;
};

export type ShortcutState = {
  shortcuts: Shortcut[];
  addShortcut: (label: string, value: string) => void;
  removeShortcut: (id: string) => void;
};

const DEFAULT_SHORTCUTS: Shortcut[] = [
  {
    id: "s1",
    label: "📝 Summarize",
    value: "Please summarize our conversation so far.",
    isCustom: false,
  },
  {
    id: "s2",
    label: "🔍 Explain",
    value: "Can you explain this in more detail?",
    isCustom: false,
  },
  {
    id: "s3",
    label: "💡 Next Steps",
    value: "What should be our next steps?",
    isCustom: false,
  },
  {
    id: "s4",
    label: "✨ Polish",
    value: "Please polish the text I just sent.",
    isCustom: false,
  },
  {
    id: "s5",
    label: "❓ Help",
    value: "What are your main capabilities?",
    isCustom: false,
  },
];

export const useShortcutStore = create<ShortcutState>()(
  persist(
    (set) => ({
      shortcuts: DEFAULT_SHORTCUTS,
      addShortcut: (label, value) =>
        set((state) => ({
          shortcuts: [
            ...state.shortcuts,
            {
              id: generateId(),
              label: `👤 ${label}`,
              value,
              isCustom: true,
            },
          ],
        })),
      removeShortcut: (id) =>
        set((state) => ({
          shortcuts: state.shortcuts.filter((s) => s.id !== id || !s.isCustom),
        })),
    }),
    {
      name: "a2a-universal-client.shortcuts",
      storage: createPersistStorage(),
    },
  ),
);
