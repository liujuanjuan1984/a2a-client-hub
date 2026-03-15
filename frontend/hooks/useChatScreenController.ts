import { TextInput } from "react-native";

import { useA2AIntegration } from "./useA2AIntegration";
import { useAgentSelection } from "./useAgentSelection";
import { useChatActions } from "./useChatActions";
import { useChatHistory } from "./useChatHistory";
import { useChatMessaging } from "./useChatMessaging";
import { useChatNavigation } from "./useChatNavigation";
import { useChatScreenFocusEffects } from "./useChatScreenFocusEffects";
import { useChatScroll } from "./useChatScroll";
import { useChatScrollRefs } from "./useChatScrollRefs";
import { useChatSession } from "./useChatSession";
import { useChatShortcut } from "./useChatShortcut";
import { useChatStates } from "./useChatStates";
import { useChatUI } from "./useChatUI";

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

  const scrollRefs = useChatScrollRefs();

  const history = useChatHistory(
    conversationId,
    session?.streamState,
    scrollRefs.scrollOffsetRef,
    scrollRefs.contentHeightRef,
  );

  const scroll = useChatScroll(
    scrollRefs,
    session?.streamState,
    history.loadMore,
  );

  useChatNavigation({ hasFetchedAgents, agent });

  const {
    session: navigationSession,
    sessionSource,
    mountedAtRef,
  } = useChatSession(conversationId, activeAgentId, history.messages);

  useChatScreenFocusEffects({
    conversationId,
    scheduleStickToBottom: scroll.scheduleStickToBottom,
    forceScrollToBottomRef: scroll.forceScrollToBottomRef,
    shouldStickToBottomRef: scroll.shouldStickToBottomRef,
    messages: history.messages,
  });

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
    scroll.scheduleStickToBottom,
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
    history,
    input: {
      ref: messaging.ref,
      value: messaging.value,
      height: messaging.height,
      maxHeight: messaging.maxHeight,
      onChange: messaging.onChange,
      onContentSizeChange: messaging.onContentSizeChange,
      onKeyPress: messaging.onKeyPress,
      onSend: messaging.onSend,
    },
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
        onUse: shortcuts.handleUseShortcut,
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
