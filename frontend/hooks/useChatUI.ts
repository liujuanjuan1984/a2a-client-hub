import { useCallback, useMemo, useState } from "react";

import { useChatActions } from "./useChatActions";

import { PAGE_TOP_OFFSET } from "@/components/layout/spacing";
import { useAppSafeArea } from "@/components/layout/useAppSafeArea";
import { type SharedModelSelection } from "@/lib/chat-utils";

export function useChatUI({
  actions,
  selectedModel,
}: {
  actions: ReturnType<typeof useChatActions>;
  selectedModel: SharedModelSelection | null;
}) {
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

  const modals = useMemo(
    () => ({
      shortcut: {
        visible: showShortcutManager,
        open: openShortcutManager,
        close: closeShortcutManager,
        onUse: actions.shortcuts.handleUseShortcut,
      },
      session: {
        visible: showSessionPicker,
        open: openSessionPicker,
        close: closeSessionPicker,
        onSelect: actions.handlers.onSessionSelect,
      },
      model: {
        visible: showModelPicker,
        open: openModelPicker,
        close: closeModelPicker,
        selectedModel,
        onSelect: actions.handlers.onModelSelect,
        onClear: actions.handlers.onModelClear,
      },
    }),
    [
      showShortcutManager,
      openShortcutManager,
      closeShortcutManager,
      showSessionPicker,
      openSessionPicker,
      closeSessionPicker,
      showModelPicker,
      openModelPicker,
      closeModelPicker,
      actions,
      selectedModel,
    ],
  );

  return {
    topInset: insets.top + PAGE_TOP_OFFSET,
    showDetails,
    toggleDetails,
    modals,
  };
}
