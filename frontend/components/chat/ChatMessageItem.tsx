import Ionicons from "@expo/vector-icons/Ionicons";
import React, { useCallback, useMemo } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { MessageBlock, MessageContentFallback } from "./MessageBlock";
import { CopyButton } from "../ui/CopyButton";

import {
  type ChatMessage,
  type MessageBlock as MessageBlockType,
} from "@/lib/api/chat-utils";
import { copyTextToClipboard, isCopyableText } from "@/lib/clipboard";

const AGENT_CONNECTIVITY_ERROR_CODES = new Set([
  "agent_unavailable",
  "timeout",
]);

const STREAM_FAILURE_ERROR_CODES = new Set([
  "stream_error",
  "stream_closed",
  "upstream_stream_error",
]);

const formatMissingParamLabel = (message: ChatMessage): string | null => {
  if (!message.missingParams?.length) {
    return null;
  }
  return message.missingParams.map((item) => item.name).join(", ");
};

const resolveErrorBannerText = (message: ChatMessage): string => {
  const normalizedErrorCode =
    typeof message.errorCode === "string" ? message.errorCode.trim() : "";
  const missingParamLabel = formatMissingParamLabel(message);

  if (missingParamLabel) {
    return `Missing required upstream parameters: ${missingParamLabel}`;
  }

  if (AGENT_CONNECTIVITY_ERROR_CODES.has(normalizedErrorCode)) {
    return "Unable to reach the upstream agent. Please try again.";
  }

  if (normalizedErrorCode === "outbound_not_allowed") {
    return "Current configuration does not allow access to this upstream agent.";
  }

  if (STREAM_FAILURE_ERROR_CODES.has(normalizedErrorCode)) {
    if (
      typeof message.errorMessage === "string" &&
      message.errorMessage.trim() &&
      (message.errorSource === "upstream_a2a" ||
        message.jsonrpcCode != null ||
        Boolean(message.upstreamError))
    ) {
      return message.errorMessage.trim();
    }
    return "Streaming response failed. Please try again.";
  }

  if (typeof message.errorMessage === "string" && message.errorMessage.trim()) {
    return message.errorMessage.trim();
  }

  return "Streaming response failed. Please try again.";
};

export const ChatMessageItem = React.memo(function ChatMessageItem({
  message,
  isLastMessage,
  sessionStreamState,
  onLayoutChangeStart,
  onLoadBlockContent,
  onRetry,
  onInterruptStream,
}: {
  message: ChatMessage;
  index: number;
  isLastMessage: boolean;
  sessionStreamState?: string | null;
  onLayoutChangeStart?: () => void;
  onLoadBlockContent?: (messageId: string, blockId: string) => Promise<boolean>;
  onRetry: () => void;
  onInterruptStream: () => void;
}) {
  const deriveRenderableBlocks = useCallback(
    (msg: ChatMessage): MessageBlockType[] => {
      const persisted = msg.blocks ?? [];
      if (persisted.length > 0) {
        return persisted;
      }
      if (msg.role === "agent" && msg.content.trim()) {
        const now = msg.createdAt;
        return [
          {
            id: `${msg.id}:text`,
            type: "text",
            content: msg.content,
            isFinished: msg.status !== "streaming",
            createdAt: now,
            updatedAt: now,
          },
        ];
      }
      return [];
    },
    [],
  );

  const textToCopy = useMemo(() => {
    return message.content.trim();
  }, [message.content]);

  const renderableBlocks = deriveRenderableBlocks(message);
  const hasBlocks = message.role === "agent" && renderableBlocks.length > 0;
  const hasPlainContent = message.content.trim().length > 0;
  const suppressFallbackWhileStreaming =
    message.role === "agent" &&
    message.status === "streaming" &&
    !hasBlocks &&
    !hasPlainContent;
  const suppressFallbackWhileError =
    message.role === "agent" &&
    message.status === "error" &&
    !hasBlocks &&
    !hasPlainContent;
  const shouldRenderMessageFallback =
    !suppressFallbackWhileStreaming && !suppressFallbackWhileError;
  const canRetry =
    isLastMessage &&
    message.role === "agent" &&
    sessionStreamState &&
    ["error", "recoverable"].includes(sessionStreamState);
  const canInterrupt =
    message.role === "agent" &&
    message.status === "streaming" &&
    sessionStreamState === "streaming";
  const canCopyMessage = isCopyableText(textToCopy);
  const userCopyButtonPositionClass = "right-0";
  let messageBody: React.ReactNode = null;
  if (hasBlocks) {
    messageBody = renderableBlocks.map((block, blockIndex) => (
      <MessageBlock
        key={block.id || `${message.id}:${blockIndex}`}
        block={block}
        messageId={message.id}
        blockIndex={blockIndex}
        role={message.role}
        messageStatus={message.status}
        onLayoutChangeStart={onLayoutChangeStart}
        onLoadBlockContent={onLoadBlockContent}
      />
    ));
  } else if (shouldRenderMessageFallback) {
    messageBody = (
      <MessageContentFallback
        hasPlainContent={hasPlainContent}
        content={message.content}
        messageId={message.id}
        role={message.role}
      />
    );
  }

  const handleLongPressCopy = useCallback(async () => {
    if (!canCopyMessage) return;

    await copyTextToClipboard(textToCopy, {
      successMessage: "Message copied to clipboard.",
      errorMessage: "Could not copy message.",
    });
  }, [canCopyMessage, textToCopy]);

  return (
    <View
      className={`mb-4 flex w-full ${
        message.role === "user" ? "items-end" : "items-start"
      }`}
    >
      <View
        className={`relative group min-w-0 ${
          message.role === "agent" ? "w-full sm:max-w-[92%]" : "max-w-[94%]"
        }`}
      >
        <Pressable
          onLongPress={canCopyMessage ? handleLongPressCopy : undefined}
          delayLongPress={500}
          className={`px-4 py-3 rounded-2xl shadow-sm ${
            message.role === "user"
              ? "bg-[#1E222D]"
              : message.role === "agent"
                ? "bg-surface"
                : "bg-slate-900"
          } ${message.role === "agent" ? "w-full" : ""} ${
            message.role === "agent" && message.status === "streaming"
              ? "min-h-[52px]"
              : ""
          }`}
        >
          {messageBody}
          {message.status === "streaming" ? (
            <View className="mt-2 flex-row items-center gap-2">
              <ActivityIndicator size="small" color="#34D399" />
              <Text className="text-[11px] font-medium italic text-neo-green/60">
                Streaming...
              </Text>
            </View>
          ) : null}
          {message.status === "error" ? (
            <View className="mt-2 flex-row items-center gap-1.5 p-2 bg-red-500/10 rounded border border-red-500/20">
              <Ionicons name="warning-outline" size={14} color="#EF4444" />
              <Text className="text-[12px] font-medium text-red-400">
                {resolveErrorBannerText(message)}
              </Text>
            </View>
          ) : null}
        </Pressable>
        <View
          className={`absolute bottom-1 ${userCopyButtonPositionClass} opacity-30`}
        >
          <CopyButton
            value={textToCopy}
            successMessage="Message copied to clipboard."
            errorMessage="Could not copy message."
            accessibilityLabel="Copy message"
            variant="ghost"
            size="sm"
            iconColor="#FFFFFF"
            disabled={!canCopyMessage}
          />
        </View>
      </View>
      {canRetry && (
        <Pressable
          onPress={onRetry}
          className="mt-2 flex-row items-center gap-1.5 opacity-60"
        >
          <Ionicons name="refresh" size={12} color="#FFFFFF" />
          <Text className="text-[11px] font-bold text-white uppercase tracking-wider">
            Retry
          </Text>
        </Pressable>
      )}
      {canInterrupt && (
        <Pressable
          testID="chat-interrupt-button"
          onPress={onInterruptStream}
          className="mt-2 flex-row items-center gap-1.5 opacity-70"
        >
          <Ionicons name="stop-circle-outline" size={12} color="#FBBF24" />
          <Text className="text-[11px] font-bold uppercase tracking-wider text-yellow-300">
            Interrupt
          </Text>
        </Pressable>
      )}
    </View>
  );
});

ChatMessageItem.displayName = "ChatMessageItem";
