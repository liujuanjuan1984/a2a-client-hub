import { useCallback, useState } from "react";

import { PAGE_TOP_OFFSET } from "@/components/layout/spacing";
import { useAppSafeArea } from "@/components/layout/useAppSafeArea";

export function useChatUI() {
  const insets = useAppSafeArea();
  const [showDetails, setShowDetails] = useState(false);
  const [showShortcutManager, setShowShortcutManager] = useState(false);
  const [showSessionPicker, setShowSessionPicker] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);

  const toggleDetails = useCallback(() => {
    setShowDetails((current) => !current);
  }, []);

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
    topInset: insets.top + PAGE_TOP_OFFSET,
    showDetails,
    toggleDetails,
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
