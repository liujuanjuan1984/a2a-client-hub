import { useChatModalStates } from "./useChatModalStates";
import { useChatScreenEssentials } from "./useChatScreenEssentials";

export function useChatUI() {
  const essentials = useChatScreenEssentials();
  const modals = useChatModalStates();

  return {
    topInset: essentials.topInset,
    showDetails: essentials.showDetails,
    toggleDetails: essentials.toggleDetails,
    modals: {
      shortcut: {
        visible: modals.showShortcutManager,
        open: modals.openShortcutManager,
        close: modals.closeShortcutManager,
      },
      session: {
        visible: modals.showSessionPicker,
        open: modals.openSessionPicker,
        close: modals.closeSessionPicker,
      },
      model: {
        visible: modals.showModelPicker,
        open: modals.openModelPicker,
        close: modals.closeModelPicker,
      },
    },
  };
}
