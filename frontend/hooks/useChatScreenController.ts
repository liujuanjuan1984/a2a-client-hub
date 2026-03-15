import { useChatDisplayState } from "./useChatDisplayState";
import { useChatNavigationState } from "./useChatNavigationState";
import { useChatOperationState } from "./useChatOperationState";

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

  const display = useChatDisplayState({
    conversationId,
    streamState: session?.streamState,
  });

  const navigation = useChatNavigationState({
    routeAgentId,
    conversationId,
    messages: display.history.messages,
  });

  const ops = useChatOperationState({
    conversationId,
    activeAgentId: navigation.activeAgentId,
    agent: navigation.agent,
    session,
    scheduleStickToBottom: display.scroll.scheduleStickToBottom,
    mountedAtRef: navigation.mountedAtRef,
  });

  return {
    navigation: {
      agent: navigation.agent,
      activeAgentId: navigation.activeAgentId,
      hasFetchedAgents: navigation.hasFetchedAgents,
      conversationId,
      session: navigation.session,
      sessionSource: navigation.sessionSource,
    },
    ui: ops.ui,
    history: display.history,
    input: {
      ref: ops.messaging.ref,
      value: ops.messaging.value,
      height: ops.messaging.height,
      maxHeight: ops.messaging.maxHeight,
      onChange: ops.messaging.onChange,
      onContentSizeChange: ops.messaging.onContentSizeChange,
      onKeyPress: ops.messaging.onKeyPress,
      onSend: ops.messaging.onSend,
    },
    scroll: {
      listRef: display.scroll.listRef,
      showScrollToBottom: display.scroll.showScrollToBottom,
      scrollToBottom: display.scroll.scrollToBottom,
      onListContentSizeChange: display.scroll.handleListContentSizeChange,
      onListScroll: display.scroll.handleListScroll,
      captureContentSizeAnchor: display.scroll.captureContentSizeAnchor,
    },
    a2a: {
      ...ops.a2a,
      pendingInterrupt: ops.states.pendingInterrupt,
    },
    modals: {
      ...ops.ui.modals,
      shortcut: {
        ...ops.ui.modals.shortcut,
        onUse: ops.shortcuts.handleUseShortcut,
      },
      session: {
        ...ops.ui.modals.session,
        onSelect: ops.actions.handleSessionSelect,
      },
      model: {
        ...ops.ui.modals.model,
        selectedModel: ops.states.selectedModel,
        onSelect: ops.actions.handleModelSelect,
        onClear: ops.actions.clearModelSelection,
      },
    },
    actions: {
      onTest: ops.actions.handleTest,
      testingConnection: ops.actions.testingConnection,
      onRetry: ops.actions.handleRetry,
    },
  };
}
