import React, { lazy, Suspense } from "react";
import { KeyboardAvoidingView, Platform, Text, View } from "react-native";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatHeaderPanel } from "@/components/chat/ChatHeaderPanel";
import { ChatTimelinePanel } from "@/components/chat/ChatTimelinePanel";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { useChatScreenController } from "@/hooks/useChatScreenController";

const LazyInvokeMetadataModal = lazy(async () => {
  const module = await import("@/components/chat/InvokeMetadataModal");
  return { default: module.InvokeMetadataModal };
});

const LazyModelPickerModal = lazy(async () => {
  const module = await import("@/components/chat/ModelPickerModal");
  return { default: module.ModelPickerModal };
});

const LazyWorkingDirectoryModal = lazy(async () => {
  const module = await import("@/components/chat/WorkingDirectoryModal");
  return { default: module.WorkingDirectoryModal };
});

const LazySessionPickerModal = lazy(async () => {
  const module = await import("@/components/chat/SessionPickerModal");
  return { default: module.SessionPickerModal };
});

const LazyShortcutManagerModal = lazy(async () => {
  const module = await import("@/components/chat/ShortcutManagerModal");
  return { default: module.ShortcutManagerModal };
});

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
        modelSelectionStatus={controller.modelSelectionStatus}
        providerDiscoveryStatus={controller.providerDiscoveryStatus}
        interruptRecoveryStatus={controller.interruptRecoveryStatus}
        sessionPromptAsyncStatus={controller.sessionPromptAsyncStatus}
        sessionAppendStatus={controller.sessionAppendStatus}
        sessionCommandStatus={controller.sessionCommandStatus}
        sessionShellStatus={controller.sessionShellStatus}
        invokeMetadataStatus={controller.invokeMetadataStatus}
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
        onInterruptStream={controller.handleInterruptStream}
        onListContentSizeChange={controller.handleListContentSizeChange}
        onListScroll={controller.handleListScroll}
        pendingInterrupt={controller.pendingInterrupt}
        pendingInterruptCount={controller.pendingInterruptCount}
        interruptAction={controller.interruptAction}
        questionAnswers={controller.questionAnswers}
        structuredResponseInput={controller.structuredResponseInput}
        onPermissionReply={controller.handlePermissionReply}
        onPermissionsReply={controller.handlePermissionsReply}
        onQuestionAnswerChange={controller.handleQuestionAnswerChange}
        onQuestionOptionPick={controller.handleQuestionOptionPick}
        onQuestionReply={controller.handleQuestionReply}
        onQuestionReject={controller.handleQuestionReject}
        onStructuredResponseChange={controller.handleStructuredResponseChange}
        onElicitationReply={controller.handleElicitationReply}
      />

      {controller.showShortcutManager ? (
        <Suspense fallback={null}>
          <LazyShortcutManagerModal
            visible
            onClose={controller.closeShortcutManager}
            onUseShortcut={controller.handleUseShortcut}
            initialPrompt={controller.shortcutManagerInitialPrompt}
            agentId={controller.activeAgentId}
          />
        </Suspense>
      ) : null}

      {controller.showSessionPicker ? (
        <Suspense fallback={null}>
          <LazySessionPickerModal
            visible
            onClose={controller.closeSessionPicker}
            agentId={controller.activeAgentId}
            currentConversationId={controller.conversationId}
            onSelect={controller.handleSessionSelect}
          />
        </Suspense>
      ) : null}

      {controller.showModelPicker ? (
        <Suspense fallback={null}>
          <LazyModelPickerModal
            visible
            onClose={controller.closeModelPicker}
            agentId={controller.activeAgentId}
            source={
              controller.agent.source === "shared" ? "shared" : "personal"
            }
            providerDiscoveryStatus={controller.providerDiscoveryStatus}
            workingDirectory={controller.workingDirectory}
            selectedModel={controller.selectedModel}
            onSelectModel={controller.handleModelSelect}
            onClearModelSelection={controller.clearModelSelection}
          />
        </Suspense>
      ) : null}

      {controller.showDirectoryPicker ? (
        <Suspense fallback={null}>
          <LazyWorkingDirectoryModal
            visible
            onClose={controller.closeDirectoryPicker}
            currentDirectory={controller.workingDirectory}
            onSave={controller.handleSaveWorkingDirectory}
            onClear={controller.handleClearWorkingDirectory}
          />
        </Suspense>
      ) : null}

      {controller.showInvokeMetadataModal ? (
        <Suspense fallback={null}>
          <LazyInvokeMetadataModal
            visible
            onClose={controller.closeInvokeMetadataModal}
            fields={controller.invokeMetadataFields}
            currentBindings={controller.invokeMetadataBindings}
            onSave={controller.handleSaveInvokeMetadata}
            onClear={controller.handleClearInvokeMetadata}
          />
        </Suspense>
      ) : null}

      <ChatComposer
        modelSelectionStatus={controller.modelSelectionStatus}
        currentDirectory={controller.workingDirectory}
        hasInvokeMetadata={controller.hasInvokeMetadataBindings}
        showInvokeMetadataControl={controller.showInvokeMetadataControl}
        invokeMetadataRequiredCount={controller.invokeMetadataRequiredCount}
        pendingInterrupt={controller.pendingInterrupt}
        pendingInterruptCount={controller.pendingInterruptCount}
        streamSendHint={controller.streamSendHint}
        showShortcutManager={controller.showShortcutManager}
        onOpenDirectoryPicker={controller.openDirectoryPicker}
        onOpenInvokeMetadata={controller.openInvokeMetadataModal}
        onOpenShortcutManager={controller.openShortcutManager}
        selectedModel={controller.selectedModel}
        onOpenModelPicker={controller.openModelPicker}
        inputRef={controller.inputRef}
        inputResetKey={controller.inputResetKey}
        inputDefaultValue={controller.inputDefaultValue}
        inputSelection={controller.inputSelection}
        hasInput={controller.hasInput}
        hasSendableInput={controller.hasSendableInput}
        maxInputChars={controller.maxInputChars}
        onClearInput={controller.clearInput}
        onInputChange={controller.handleInputChange}
        onSelectionChange={controller.handleSelectionChange}
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
