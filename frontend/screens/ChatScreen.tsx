import React from "react";
import { KeyboardAvoidingView, Platform, Text, View } from "react-native";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatHeaderPanel } from "@/components/chat/ChatHeaderPanel";
import { ChatTimelinePanel } from "@/components/chat/ChatTimelinePanel";
import { ModelPickerModal } from "@/components/chat/ModelPickerModal";
import { SessionPickerModal } from "@/components/chat/SessionPickerModal";
import { ShortcutManagerModal } from "@/components/chat/ShortcutManagerModal";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { useChatScreenController } from "@/hooks/useChatScreenController";

export function ChatScreen({
  agentId: routeAgentId,
  conversationId,
}: {
  agentId?: string | null;
  conversationId?: string;
}) {
  const controller = useChatScreenController({
    routeAgentId,
    conversationId,
  });

  if (!controller.navigation.agent) {
    if (!controller.navigation.hasFetchedAgents) {
      return <FullscreenLoader message="Restoring session..." />;
    }
    return (
      <View className="flex-1 items-center justify-center bg-background px-4">
        <Text className="text-xl font-bold text-black">
          Select an agent first
        </Text>
        <Text className="mt-2 text-center text-sm text-black">
          Choose an agent from the list to start chatting.
        </Text>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      className="flex-1 bg-background"
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ChatHeaderPanel
        topInset={controller.ui.topInset}
        agent={controller.navigation.agent}
        conversationId={controller.navigation.conversationId}
        sessionSource={controller.navigation.sessionSource}
        session={controller.navigation.session}
        showDetails={controller.ui.showDetails}
        onToggleDetails={controller.ui.toggleDetails}
        onOpenSessionPicker={controller.modals.session.open}
        onTestConnection={controller.actions.onTest}
        testingConnection={controller.actions.testingConnection}
      />

      <ChatTimelinePanel
        listRef={controller.scroll.listRef}
        messages={controller.history.messages}
        session={controller.navigation.session}
        historyNextPage={controller.history.nextPage}
        historyLoadingMore={controller.history.loadingMore}
        historyPaused={controller.history.paused}
        onLoadEarlierHistory={controller.history.loadMore}
        historyLoading={controller.history.loading}
        historyError={controller.history.error}
        onCaptureContentSizeAnchor={controller.scroll.captureContentSizeAnchor}
        onLoadBlockContent={controller.history.handleLoadBlockContent}
        onRetry={controller.actions.onRetry}
        onListContentSizeChange={controller.scroll.onListContentSizeChange}
        onListScroll={controller.scroll.onListScroll}
        pendingInterrupt={controller.a2a.pendingInterrupt}
        interruptAction={controller.a2a.interruptAction}
        questionAnswers={controller.a2a.questionAnswers}
        onPermissionReply={controller.a2a.handlePermissionReply}
        onQuestionAnswerChange={controller.a2a.handleQuestionAnswerChange}
        onQuestionOptionPick={controller.a2a.handleQuestionOptionPick}
        onQuestionReply={controller.a2a.handleQuestionReply}
        onQuestionReject={controller.a2a.handleQuestionReject}
      />

      <ShortcutManagerModal
        visible={controller.modals.shortcut.visible}
        onClose={controller.modals.shortcut.close}
        onUseShortcut={controller.modals.shortcut.onUse}
        initialPrompt={controller.input.value}
        agentId={controller.navigation.activeAgentId}
      />

      <SessionPickerModal
        visible={controller.modals.session.visible}
        onClose={controller.modals.session.close}
        agentId={controller.navigation.activeAgentId}
        currentConversationId={controller.navigation.conversationId}
        onSelect={controller.modals.session.onSelect}
      />

      <ModelPickerModal
        visible={controller.modals.model.visible}
        onClose={controller.modals.model.close}
        agentId={controller.navigation.activeAgentId}
        source={controller.navigation.agent.source}
        sessionMetadata={controller.navigation.session?.metadata}
        selectedModel={controller.modals.model.selectedModel}
        onSelectModel={controller.modals.model.onSelect}
        onClearModelSelection={controller.modals.model.onClear}
      />

      <ChatComposer
        pendingInterrupt={controller.a2a.pendingInterrupt}
        showShortcutManager={controller.modals.shortcut.visible}
        onOpenShortcutManager={controller.modals.shortcut.open}
        selectedModel={controller.modals.model.selectedModel}
        onOpenModelPicker={controller.modals.model.open}
        inputRef={controller.input.ref}
        input={controller.input.value}
        onInputChange={controller.input.onChange}
        onContentSizeChange={controller.input.onContentSizeChange}
        inputHeight={controller.input.height}
        maxInputHeight={controller.input.maxHeight}
        onSubmit={controller.input.onSend}
        onKeyPress={controller.input.onKeyPress}
        showScrollToBottom={controller.scroll.showScrollToBottom}
        onScrollToBottom={() => controller.scroll.scrollToBottom(true)}
      />
    </KeyboardAvoidingView>
  );
}
