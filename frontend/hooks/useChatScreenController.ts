import { type TextInput } from "react-native";

import { useA2AIntegration } from "./useA2AIntegration";
import { useAgentSelection } from "./useAgentSelection";
import { useChatActions } from "./useChatActions";
import { useChatModals } from "./useChatModals";
import { useChatNavigation } from "./useChatNavigation";
import { useChatSession } from "./useChatSession";
import { useChatShortcut } from "./useChatShortcut";
import { useChatTimeline } from "./useChatTimeline";
import { useChatUI } from "./useChatUI";
import { useSessionBinding } from "./useSessionBinding";

export function useChatScreenController({
  routeAgentId,
  conversationId,
}: {
  routeAgentId?: string | null;
  conversationId?: string;
}) {
  const { activeAgentId, agent, hasFetchedAgents } =
    useAgentSelection(routeAgentId);

  const { session, sessionSource, selectedModel } = useChatSession(
    conversationId,
    activeAgentId,
  );

  const { history, scroll } = useChatTimeline({
    conversationId,
    streamState: session?.streamState,
  });

  useSessionBinding({
    conversationId,
    activeAgentId,
    sessionSource,
    messages: history.messages,
  });

  useChatNavigation({ hasFetchedAgents, agent });

  const ui = useChatUI();

  const actions = useChatActions({
    conversationId,
    agent,
    scheduleStickToBottom: scroll.scheduleStickToBottom,
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

  const a2a = useA2AIntegration({
    conversationId,
    agent,
  });

  return {
    navigation: {
      agent,
      activeAgentId,
      hasFetchedAgents,
      conversationId,
      session,
      sessionSource,
    },
    ui,
    history,
    input: actions.input,
    scroll: scroll.props,
    a2a,
    modals,
    actions: {
      onTest: actions.handlers.onTest,
      testingConnection: actions.testingConnection,
      onRetry: actions.handlers.onRetry,
    },
  };
}
