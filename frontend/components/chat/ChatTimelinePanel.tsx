import React, { useCallback, useMemo } from "react";
import {
  ActivityIndicator,
  FlatList,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
  Text,
  View,
} from "react-native";

import { ChatMessageItem } from "./ChatMessageItem";

import { InterruptActionCard } from "@/components/chat/InterruptActionCard";
import { Button } from "@/components/ui/Button";
import {
  type ChatMessage,
  type PendingRuntimeInterrupt,
} from "@/lib/api/chat-utils";
import { type AgentSession } from "@/lib/chat-utils";

const LIST_INITIAL_NUM_TO_RENDER = 16;
const LIST_WINDOW_SIZE = 9;
const LIST_MAX_TO_RENDER_PER_BATCH = 20;
const LIST_CONTENT_CONTAINER_STYLE = { paddingBottom: 24 };

export function ChatTimelinePanel({
  listRef,
  messages,
  session,
  historyNextPage,
  historyLoadingMore,
  historyPaused,
  onLoadEarlierHistory,
  historyLoading,
  historyError,
  onCaptureContentSizeAnchor,
  onLoadBlockContent,
  onRetry,
  onInterruptStream,
  onListContentSizeChange,
  onListScroll,
  pendingInterrupt,
  pendingInterruptCount,
  interruptAction,
  questionAnswers,
  onPermissionReply,
  onQuestionAnswerChange,
  onQuestionOptionPick,
  onQuestionReply,
  onQuestionReject,
}: {
  listRef: React.RefObject<FlatList<ChatMessage> | null>;
  messages: ChatMessage[];
  session?: AgentSession;
  historyNextPage?: number | null;
  historyLoadingMore: boolean;
  historyPaused: boolean;
  onLoadEarlierHistory: () => void;
  historyLoading: boolean;
  historyError: string | null;
  onCaptureContentSizeAnchor: () => void;
  onLoadBlockContent: (messageId: string, blockId: string) => Promise<boolean>;
  onRetry: () => void;
  onInterruptStream: () => void;
  onListContentSizeChange: (w: number, h: number) => void;
  onListScroll: (event: NativeSyntheticEvent<NativeScrollEvent>) => void;
  pendingInterrupt: PendingRuntimeInterrupt | null;
  pendingInterruptCount: number;
  interruptAction: string | null;
  questionAnswers: string[];
  onPermissionReply: (reply: "once" | "always" | "reject") => void;
  onQuestionAnswerChange: (index: number, value: string) => void;
  onQuestionOptionPick: (index: number, value: string) => void;
  onQuestionReply: () => void;
  onQuestionReject: () => void;
}) {
  const keyExtractor = useCallback((item: ChatMessage) => item.id, []);
  const renderMessageItem = useCallback(
    ({ item, index }: { item: ChatMessage; index: number }) => (
      <ChatMessageItem
        message={item}
        index={index}
        isLastMessage={index === messages.length - 1}
        sessionStreamState={session?.streamState}
        onLayoutChangeStart={onCaptureContentSizeAnchor}
        onLoadBlockContent={onLoadBlockContent}
        onRetry={onRetry}
        onInterruptStream={onInterruptStream}
      />
    ),
    [
      messages.length,
      onCaptureContentSizeAnchor,
      onLoadBlockContent,
      onInterruptStream,
      onRetry,
      session?.streamState,
    ],
  );
  const listHeaderComponent = useMemo(
    () =>
      typeof historyNextPage === "number" ? (
        <View className="items-center">
          <Button
            className="mt-2"
            label={historyLoadingMore ? "Loading..." : "Load earlier"}
            size="sm"
            variant="secondary"
            loading={historyLoadingMore}
            disabled={historyPaused}
            onPress={onLoadEarlierHistory}
          />
        </View>
      ) : null,
    [historyLoadingMore, historyNextPage, historyPaused, onLoadEarlierHistory],
  );
  const listEmptyComponent = useMemo(
    () => (
      <View className="mt-12 items-center">
        <Text className="text-sm text-muted">
          {historyLoading
            ? "Loading history..."
            : historyError
              ? historyError
              : "No messages yet."}
        </Text>
      </View>
    ),
    [historyError, historyLoading],
  );
  const listFooterComponent = useMemo(
    () =>
      pendingInterrupt ? (
        <InterruptActionCard
          pendingInterrupt={pendingInterrupt}
          pendingInterruptCount={pendingInterruptCount}
          interruptAction={interruptAction}
          questionAnswers={questionAnswers}
          onPermissionReply={onPermissionReply}
          onQuestionAnswerChange={onQuestionAnswerChange}
          onQuestionOptionPick={onQuestionOptionPick}
          onQuestionReply={onQuestionReply}
          onQuestionReject={onQuestionReject}
        />
      ) : null,
    [
      interruptAction,
      onPermissionReply,
      onQuestionAnswerChange,
      onQuestionOptionPick,
      onQuestionReject,
      onQuestionReply,
      pendingInterrupt,
      pendingInterruptCount,
      questionAnswers,
    ],
  );

  return (
    <>
      {session?.streamState === "recoverable" ? (
        <View className="mx-2 sm:mx-6 mt-3 flex-row items-center rounded-xl border border-yellow-500/30 bg-yellow-500/10 px-3 py-2">
          <ActivityIndicator size="small" color="#fcd34d" className="mr-2" />
          <Text className="text-xs text-yellow-300">
            Connection lost. Trying to recover the stream...
          </Text>
        </View>
      ) : null}

      {session?.streamState === "error" ? (
        <View className="mx-2 sm:mx-6 mt-3 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2">
          <Text className="text-xs text-red-300">
            Session recovery failed.
            {session.lastStreamError ? ` ${session.lastStreamError}` : ""}
          </Text>
        </View>
      ) : null}

      <FlatList
        ref={listRef}
        className="mt-2 flex-1 px-2 sm:px-6"
        data={messages ?? []}
        keyExtractor={keyExtractor}
        renderItem={renderMessageItem}
        contentContainerStyle={LIST_CONTENT_CONTAINER_STYLE}
        keyboardShouldPersistTaps="handled"
        initialNumToRender={LIST_INITIAL_NUM_TO_RENDER}
        maxToRenderPerBatch={LIST_MAX_TO_RENDER_PER_BATCH}
        windowSize={LIST_WINDOW_SIZE}
        updateCellsBatchingPeriod={50}
        removeClippedSubviews={Platform.OS === "android"}
        onContentSizeChange={onListContentSizeChange}
        onScroll={onListScroll}
        scrollEventThrottle={16}
        ListHeaderComponent={listHeaderComponent}
        ListEmptyComponent={listEmptyComponent}
        ListFooterComponent={listFooterComponent}
      />
    </>
  );
}
