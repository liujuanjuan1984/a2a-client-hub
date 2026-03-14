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

  if (!controller.agent) {
    if (!controller.hasFetchedAgents) {
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
        topInset={controller.topInset}
        agent={controller.agent}
        conversationId={controller.conversationId}
        sessionSource={controller.sessionSource}
        session={controller.session}
        showDetails={controller.showDetails}
        onToggleDetails={controller.toggleDetails}
        onOpenSessionPicker={controller.openSessionPicker}
        onTestConnection={controller.handleTest}
        testingConnection={controller.testingConnection}
      />

      <ChatTimelinePanel
        listRef={controller.listRef}
        messages={controller.messages}
        session={controller.session}
        historyNextPage={controller.historyNextPage}
        historyLoadingMore={controller.historyLoadingMore}
        historyPaused={controller.historyPaused}
        onLoadEarlierHistory={controller.loadEarlierHistory}
        historyLoading={controller.historyLoading}
        historyError={controller.historyError}
        onCaptureContentSizeAnchor={controller.captureContentSizeAnchor}
        onLoadBlockContent={controller.handleLoadBlockContent}
        onRetry={controller.handleRetry}
        onListContentSizeChange={controller.handleListContentSizeChange}
        onListScroll={controller.handleListScroll}
        pendingInterrupt={controller.pendingInterrupt}
        interruptAction={controller.interruptAction}
        questionAnswers={controller.questionAnswers}
        onPermissionReply={controller.handlePermissionReply}
        onQuestionAnswerChange={controller.handleQuestionAnswerChange}
        onQuestionOptionPick={controller.handleQuestionOptionPick}
        onQuestionReply={controller.handleQuestionReply}
        onQuestionReject={controller.handleQuestionReject}
      />

      <ShortcutManagerModal
        visible={controller.showShortcutManager}
        onClose={controller.closeShortcutManager}
        onUseShortcut={controller.handleUseShortcut}
        initialPrompt={controller.input}
        agentId={controller.activeAgentId}
      />

      <SessionPickerModal
        visible={controller.showSessionPicker}
        onClose={controller.closeSessionPicker}
        agentId={controller.activeAgentId}
        currentConversationId={controller.conversationId}
        onSelect={controller.handleSessionSelect}
      />

      <ModelPickerModal
        visible={controller.showModelPicker}
        onClose={controller.closeModelPicker}
        agentId={controller.activeAgentId}
        source={controller.agent.source}
        sessionMetadata={controller.session?.metadata}
        selectedModel={controller.selectedModel}
        onSelectModel={controller.handleModelSelect}
        onClearModelSelection={controller.clearModelSelection}
      />

      <ChatComposer
        supportsOpencodeDiscovery={controller.supportsOpencodeDiscovery}
        pendingInterrupt={controller.pendingInterrupt}
        showShortcutManager={controller.showShortcutManager}
        onOpenShortcutManager={controller.openShortcutManager}
        selectedModel={controller.selectedModel}
        onOpenModelPicker={controller.openModelPicker}
        inputRef={controller.inputRef}
        input={controller.input}
        onInputChange={controller.handleInputChange}
        onContentSizeChange={controller.handleContentSizeChange}
        inputHeight={controller.inputHeight}
        maxInputHeight={controller.maxInputHeight}
        onSubmit={controller.handleSend}
        onKeyPress={controller.handleKeyPress}
        showScrollToBottom={controller.showScrollToBottom}
        onScrollToBottom={() => controller.scrollToBottom(true)}
      />
    </KeyboardAvoidingView>
  );
}
