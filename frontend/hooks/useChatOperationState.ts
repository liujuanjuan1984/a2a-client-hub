import { TextInput } from "react-native";

import { useA2AIntegration } from "./useA2AIntegration";
import { useChatActions } from "./useChatActions";
import { useChatMessaging } from "./useChatMessaging";
import { useChatShortcut } from "./useChatShortcut";
import { useChatStates } from "./useChatStates";
import { useChatUI } from "./useChatUI";

import { type AgentSession } from "@/lib/chat-utils";
import { type AgentConfig } from "@/store/agents";

export function useChatOperationState({
  conversationId,
  activeAgentId,
  agent,
  session,
  scheduleStickToBottom,
  mountedAtRef,
}: {
  conversationId?: string;
  activeAgentId: string | null;
  agent: AgentConfig | undefined;
  session: AgentSession | undefined;
  scheduleStickToBottom: (animated: boolean) => void;
  mountedAtRef: React.MutableRefObject<number>;
}) {
  const states = useChatStates({ session });
  const ui = useChatUI();

  const messaging = useChatMessaging((text) =>
    actions.handleSend(text, states.pendingInterrupt),
  );

  const actions = useChatActions(
    conversationId,
    activeAgentId,
    agent,
    session,
    scheduleStickToBottom,
    messaging.clear,
  );

  const a2a = useA2AIntegration(
    conversationId,
    activeAgentId,
    agent,
    states.pendingInterrupt,
    states.lastResolvedInterrupt,
    mountedAtRef,
  );

  const shortcuts = useChatShortcut({
    setInput: messaging.setInput,
    closeShortcutManager: ui.modals.shortcut.close,
    inputRef: messaging.ref as React.RefObject<TextInput>,
  });

  return { states, ui, messaging, actions, a2a, shortcuts };
}
