import { useA2AIntegration } from "./useA2AIntegration";
import { useAgentSelection } from "./useAgentSelection";
import { useChatActions } from "./useChatActions";
import { useChatNavigation } from "./useChatNavigation";
import { useChatScroll } from "./useChatScroll";
import { useChatSession } from "./useChatSession";
import { useChatUI } from "./useChatUI";
import { useMessageState } from "./useMessageState";
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

  const messageState = useMessageState(conversationId);

  const { session, sessionSource, selectedModel } = useChatSession(
    conversationId,
    activeAgentId,
  );

  useSessionBinding({
    conversationId,
    activeAgentId,
    sessionSource,
    messages: messageState.messages,
  });

  const scroll = useChatScroll({
    conversationId,
    streamState: session?.streamState,
    messages: messageState.messages,
    onLoadEarlier: messageState.loadMore,
  });

  useChatNavigation({ hasFetchedAgents, agent });

  const ui = useChatUI();

  const actions = useChatActions({
    conversationId,
    agent,
    scheduleStickToBottom: scroll.scheduleStickToBottom,
    onShortcutUsed: () => ui.modals.shortcut.close(),
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
    history: messageState,
    input: actions.input,
    scroll: scroll.props,
    a2a,
    modals: {
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
    },
    actions: {
      onTest: actions.handlers.onTest,
      testingConnection: actions.testingConnection,
      onRetry: actions.handlers.onRetry,
    },
  };
}
