import { TextInput } from "react-native";

import { useA2AIntegration } from "./useA2AIntegration";
import { useAgentSelection } from "./useAgentSelection";
import { useChatActions } from "./useChatActions";
import { useChatInput } from "./useChatInput";
import { useChatModalStates } from "./useChatModalStates";
import { useChatNavigation } from "./useChatNavigation";
import { useChatScreenEssentials } from "./useChatScreenEssentials";
import { useChatScreenFocusEffects } from "./useChatScreenFocusEffects";
import { useChatScroll } from "./useChatScroll";
import { useChatSession } from "./useChatSession";
import { useChatShortcut } from "./useChatShortcut";
import { useChatStates } from "./useChatStates";
import { useMessageState } from "./useMessageState";

import { useChatStore } from "@/store/chat";

export function useChatScreenController({
  routeAgentId,
  conversationId,
}: {
  routeAgentId?: string | null;
  conversationId?: string;
}) {
  const { activeAgentId, agent, hasFetchedAgents } =
    useAgentSelection(routeAgentId);

  useChatNavigation({ hasFetchedAgents, agent });

  const essentials = useChatScreenEssentials();

  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );
  const historyPaused = session?.streamState === "streaming";

  const states = useChatStates({ session });

  const messageState = useMessageState(conversationId, historyPaused);

  const { sessionSource, mountedAtRef } = useChatSession(
    conversationId,
    activeAgentId,
    messageState.messages,
  );

  const scroll = useChatScroll(
    messageState.messages.length,
    session?.streamState,
    () =>
      messageState.loadEarlierHistory(
        scroll.scrollOffsetRef.current,
        scroll.contentHeightRef.current,
      ),
  );

  useChatScreenFocusEffects({
    conversationId,
    scheduleStickToBottom: scroll.scheduleStickToBottom,
    forceScrollToBottomRef: scroll.forceScrollToBottomRef,
    shouldStickToBottomRef: scroll.shouldStickToBottomRef,
    messages: messageState.messages,
  });

  const input = useChatInput(() =>
    actions.handleSend(input.input, states.pendingInterrupt),
  );

  const actions = useChatActions(
    conversationId,
    activeAgentId,
    agent,
    session,
    scroll.scheduleStickToBottom,
    input.clearInput,
  );

  const a2a = useA2AIntegration(
    conversationId,
    activeAgentId,
    agent,
    states.pendingInterrupt,
    states.lastResolvedInterrupt,
    mountedAtRef,
  );

  const modals = useChatModalStates();

  const shortcuts = useChatShortcut({
    setInput: input.setInput,
    closeShortcutManager: modals.closeShortcutManager,
    inputRef: input.inputRef as React.RefObject<TextInput>,
  });

  return {
    topInset: essentials.topInset,
    agent,
    activeAgentId,
    hasFetchedAgents,
    conversationId,
    session,
    sessionSource,
    selectedModel: states.selectedModel,
    messages: messageState.messages,
    historyLoading: messageState.historyLoading,
    historyLoadingMore: messageState.historyLoadingMore,
    historyNextPage: messageState.historyNextPage,
    historyPaused: session?.streamState === "streaming",
    historyError: messageState.historyError,
    pendingInterrupt: states.pendingInterrupt,
    interruptAction: a2a.interruptAction,
    questionAnswers: a2a.questionAnswers,
    showDetails: essentials.showDetails,
    toggleDetails: essentials.toggleDetails,
    showScrollToBottom: scroll.showScrollToBottom,
    scrollToBottom: scroll.scrollToBottom,
    showShortcutManager: modals.showShortcutManager,
    showSessionPicker: modals.showSessionPicker,
    showModelPicker: modals.showModelPicker,
    openShortcutManager: modals.openShortcutManager,
    closeShortcutManager: modals.closeShortcutManager,
    openSessionPicker: modals.openSessionPicker,
    closeSessionPicker: modals.closeSessionPicker,
    openModelPicker: modals.openModelPicker,
    closeModelPicker: modals.closeModelPicker,
    handleModelSelect: actions.handleModelSelect,
    clearModelSelection: actions.clearModelSelection,
    handleUseShortcut: shortcuts.handleUseShortcut,
    handleSessionSelect: actions.handleSessionSelect,
    handleTest: actions.handleTest,
    testingConnection: actions.testingConnection,
    listRef: scroll.listRef,
    inputRef: input.inputRef,
    input: input.input,
    inputHeight: input.inputHeight,
    maxInputHeight: input.maxInputHeight,
    handleInputChange: input.handleInputChange,
    handleContentSizeChange: input.handleContentSizeChange,
    handleKeyPress: input.handleKeyPress,
    handleSend: () => actions.handleSend(input.input, states.pendingInterrupt),
    loadEarlierHistory: () =>
      messageState.loadEarlierHistory(
        scroll.scrollOffsetRef.current,
        scroll.contentHeightRef.current,
      ),
    handleListContentSizeChange: scroll.handleListContentSizeChange,
    handleListScroll: scroll.handleListScroll,
    captureContentSizeAnchor: scroll.captureContentSizeAnchor,
    handleLoadBlockContent: messageState.handleLoadBlockContent,
    handleRetry: actions.handleRetry,
    handlePermissionReply: a2a.handlePermissionReply,
    handleQuestionAnswerChange: a2a.handleQuestionAnswerChange,
    handleQuestionOptionPick: a2a.handleQuestionOptionPick,
    handleQuestionReply: a2a.handleQuestionReply,
    handleQuestionReject: a2a.handleQuestionReject,
  };
}
