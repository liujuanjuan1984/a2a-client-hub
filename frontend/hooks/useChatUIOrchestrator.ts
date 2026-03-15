import { type TextInput } from "react-native";

import { useChatActions } from "@/hooks/useChatActions";
import { useChatModals } from "@/hooks/useChatModals";
import { useChatShortcut } from "@/hooks/useChatShortcut";
import { useChatUI } from "@/hooks/useChatUI";
import { type SharedModelSelection } from "@/lib/chat-utils";
import { type AgentConfig } from "@/store/agents";

export function useChatUIOrchestrator({
  conversationId,
  agent,
  scheduleStickToBottom,
  selectedModel,
}: {
  conversationId: string | undefined;
  agent: AgentConfig | undefined;
  scheduleStickToBottom: (animated: boolean) => void;
  selectedModel: SharedModelSelection | null;
}) {
  const ui = useChatUI();

  const actions = useChatActions({
    conversationId,
    agent,
    scheduleStickToBottom,
  });

  const shortcuts = useChatShortcut({
    setInput: actions.input.setInput,
    closeShortcutManager: () => ui.modals.shortcut.close(),
    inputRef: actions.input.ref as React.RefObject<TextInput>,
  });

  const modals = useChatModals({
    ui,
    handlers: actions.handlers,
    shortcuts,
    selectedModel,
  });

  return {
    ui,
    input: actions.input,
    modals,
    actions: {
      onTest: actions.handlers.onTest,
      testingConnection: actions.testingConnection,
      onRetry: actions.handlers.onRetry,
    },
  };
}
