import { useA2AIntegration } from "./useA2AIntegration";
import { useAgentSelection } from "./useAgentSelection";
import { useChatActions } from "./useChatActions";
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

  // We call useMessageState first to get messages for useChatSession binding check
  // It needs streamState which we can get from useChatSession return, but that's circular.
  // Actually, useChatSession already subscribes to the session.
  // Let's just have useChatSession return the session and we use it.

  // To break the circle: useChatSession handles the binding and session state.
  // We'll pass messageState.messages to it for the effect.
  const messageState = useMessageState(conversationId, undefined); // We'll fix this hook next

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

  const a2a = useA2AIntegration(
    conversationId,
    activeAgentId,
    agent,
    pendingInterrupt,
    lastResolvedInterrupt,
    mountedAtRef,
  );

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
    scroll: {
      listRef: scroll.listRef,
      showScrollToBottom: scroll.showScrollToBottom,
      scrollToBottom: scroll.scrollToBottom,
      onListContentSizeChange: scroll.handleListContentSizeChange,
      onListScroll: scroll.handleListScroll,
      captureContentSizeAnchor: scroll.captureContentSizeAnchor,
    },
    a2a: {
      ...a2a,
      pendingInterrupt,
    },
    modals: {
      ...ui.modals,
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
