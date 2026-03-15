import { useCallback, useState } from "react";

export function useChatModalStates() {
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
    showShortcutManager,
    openShortcutManager,
    closeShortcutManager,
    showSessionPicker,
    openSessionPicker,
    closeSessionPicker,
    showModelPicker,
    openModelPicker,
    closeModelPicker,
  };
}
