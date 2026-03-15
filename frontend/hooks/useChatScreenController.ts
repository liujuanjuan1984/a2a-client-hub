import { useA2AIntegration } from "./useA2AIntegration";
import { useAgentSelection } from "./useAgentSelection";
import { useChatActions } from "./useChatActions";
import { useChatNavigation } from "./useChatNavigation";
import { useChatScreenFocusEffects } from "./useChatScreenFocusEffects";
import { useChatScroll } from "./useChatScroll";
import { useChatSession } from "./useChatSession";
import { useChatStates } from "./useChatStates";
import { useChatUI } from "./useChatUI";
import { useMessageState } from "./useMessageState";

import { useChatStore } from "@/store/chat";

export function useChatScreenController({
  routeAgentId,
  conversationId,
}: {
  routeAgentId?: string | null;
  conversationId?: string;
}) {
  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );

  const { activeAgentId, agent, hasFetchedAgents } =
    useAgentSelection(routeAgentId);

  const messageState = useMessageState(conversationId, session?.streamState);

  const scroll = useChatScroll(
    messageState.refs,
    session?.streamState,
    messageState.loadMore,
  );

  useChatNavigation({ hasFetchedAgents, agent });

  const {
    session: navigationSession,
    sessionSource,
    mountedAtRef,
  } = useChatSession(conversationId, activeAgentId, messageState.messages);

  useChatScreenFocusEffects({
    conversationId,
    scheduleStickToBottom: scroll.scheduleStickToBottom,
    forceScrollToBottomRef: scroll.forceScrollToBottomRef,
    shouldStickToBottomRef: scroll.shouldStickToBottomRef,
    messages: messageState.messages,
  });

  const states = useChatStates({ session });
  const ui = useChatUI();

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
    states.pendingInterrupt,
    states.lastResolvedInterrupt,
    mountedAtRef,
  );

  return {
    navigation: {
      agent,
      activeAgentId,
      hasFetchedAgents,
      conversationId,
      session: navigationSession,
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
      pendingInterrupt: states.pendingInterrupt,
    },
    modals: {
      ...ui.modals,
      shortcut: {
        ...ui.modals.shortcut,
        onUse: actions.shortcuts.handleUseShortcut,
      },
      session: {
        ...ui.modals.session,
        onSelect: actions.handleSessionSelect,
      },
      model: {
        ...ui.modals.model,
        selectedModel: states.selectedModel,
        onSelect: actions.handleModelSelect,
        onClear: actions.clearModelSelection,
      },
    },
    actions: {
      onTest: actions.handleTest,
      testingConnection: actions.testingConnection,
      onRetry: actions.handleRetry,
    },
  };
}
