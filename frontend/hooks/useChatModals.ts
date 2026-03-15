import { useMemo } from "react";

import { useChatActions } from "./useChatActions";
import { useChatUI } from "./useChatUI";

import { type SharedModelSelection } from "@/lib/chat-utils";

export function useChatModals({
  ui,
  actions,
  selectedModel,
}: {
  ui: ReturnType<typeof useChatUI>;
  actions: ReturnType<typeof useChatActions>;
  selectedModel: SharedModelSelection | null;
}) {
  return useMemo(
    () => ({
      ...ui.modals,
      shortcut: {
        ...ui.modals.shortcut,
        onUse: actions.shortcuts.handleUseShortcut,
      },
      session: {
        ...ui.modals.session,
        onSelect: actions.handlers.onSessionSelect,
      },
      model: {
        ...ui.modals.model,
        selectedModel,
        onSelect: actions.handlers.onModelSelect,
        onClear: actions.handlers.onModelClear,
      },
    }),
    [ui.modals, actions, selectedModel],
  );
}
