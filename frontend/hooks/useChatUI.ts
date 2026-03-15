import { useCallback, useState } from "react";

import { useChatScreenEssentials } from "./useChatScreenEssentials";

export function useChatUI() {
  const essentials = useChatScreenEssentials();

  const [showShortcutManager, setShowShortcutManager] = useState(false);
  const [showSessionPicker, setShowSessionPicker] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);

  const openShortcutManager = useCallback(() => {
    setShowShortcutManager(true);
  }, []);

  const closeShortcutManager = useCallback(() => {
    setShowShortcutManager(false);
  }, []);

  const openSessionPicker = useCallback(() => {
    setShowSessionPicker(true);
  }, []);

  const closeSessionPicker = useCallback(() => {
    setShowSessionPicker(false);
  }, []);

  const openModelPicker = useCallback(() => {
    setShowModelPicker(true);
  }, []);

  const closeModelPicker = useCallback(() => {
    setShowModelPicker(false);
  }, []);

  return {
    topInset: essentials.topInset,
    showDetails: essentials.showDetails,
    toggleDetails: essentials.toggleDetails,
    modals: {
      shortcut: {
        visible: showShortcutManager,
        open: openShortcutManager,
        close: closeShortcutManager,
      },
      session: {
        visible: showSessionPicker,
        open: openSessionPicker,
        close: closeSessionPicker,
      },
      model: {
        visible: showModelPicker,
        open: openModelPicker,
        close: closeModelPicker,
      },
    },
  };
}
