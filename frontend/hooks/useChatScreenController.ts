import { useA2AIntegration } from "./useA2AIntegration";
import { useAgentSelection } from "./useAgentSelection";
import { useChatActions } from "./useChatActions";
import { useChatModals } from "./useChatModals";
import { useChatNavigation } from "./useChatNavigation";
import { useChatScreenFocusEffects } from "./useChatScreenFocusEffects";
import { useChatScroll } from "./useChatScroll";
import { useChatSession } from "./useChatSession";
import { useChatUI } from "./useChatUI";
import { useMessageState } from "./useMessageState";

export function useChatScreenController({
  routeAgentId,
  conversationId,
}: {
  routeAgentId?: string | null;
  conversationId?: string;
}) {
  const { activeAgentId, agent, hasFetchedAgents } =
    useAgentSelection(routeAgentId);

  const ui = useChatUI();

  // We call useMessageState first to get messages for useChatSession binding check.
  // To break the circular dependency with streamState, useMessageState internally
  // subscribes to the session state when streamState parameter is omitted.
  const messageState = useMessageState(conversationId);

  const {
    session,
    sessionSource,
    mountedAtRef,
    pendingInterrupt,
    lastResolvedInterrupt,
    selectedModel,
  } = useChatSession(conversationId, activeAgentId, messageState.messages);

  const scroll = useChatScroll(session?.streamState, messageState.loadMore);

  useChatNavigation({ hasFetchedAgents, agent });

  useChatScreenFocusEffects({
    conversationId,
    scheduleStickToBottom: scroll.scheduleStickToBottom,
    forceScrollToBottomRef: scroll.forceScrollToBottomRef,
    shouldStickToBottomRef: scroll.shouldStickToBottomRef,
    messages: messageState.messages,
  });

  const actions = useChatActions({
    conversationId,
    activeAgentId,
    agent,
    session,
    scheduleStickToBottom: scroll.scheduleStickToBottom,
    closeShortcutManager: ui.modals.shortcut.close,
  });

  const a2a = useA2AIntegration({
    conversationId,
    activeAgentId,
    agent,
    pendingInterrupt,
    lastResolvedInterrupt,
    mountedAtRef,
  });

  const modals = useChatModals({ ui, actions, selectedModel });

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
    modals,
    actions: {
      onTest: actions.handlers.onTest,
      testingConnection: actions.testingConnection,
      onRetry: actions.handlers.onRetry,
    },
  };
}
