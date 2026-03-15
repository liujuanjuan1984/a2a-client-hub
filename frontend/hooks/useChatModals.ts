import { type useChatActions } from "./useChatActions";
import { type useChatShortcut } from "./useChatShortcut";
import { type useChatUI } from "./useChatUI";

import { type SharedModelSelection } from "@/lib/chat-utils";

export function useChatModals({
  ui,
  handlers,
  shortcuts,
  selectedModel,
}: {
  ui: ReturnType<typeof useChatUI>;
  handlers: ReturnType<typeof useChatActions>["handlers"];
  shortcuts: ReturnType<typeof useChatShortcut>;
  selectedModel: SharedModelSelection | null;
}) {
  return {
    shortcut: {
      ...ui.modals.shortcut,
      onUse: shortcuts.handleUseShortcut,
    },
    session: {
      ...ui.modals.session,
      onSelect: handlers.onSessionSelect,
    },
    model: {
      ...ui.modals.model,
      selectedModel,
      onSelect: handlers.onModelSelect,
      onClear: handlers.onModelClear,
    },
  };
}
