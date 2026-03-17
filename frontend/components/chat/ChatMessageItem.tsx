import { Ionicons } from "@expo/vector-icons";
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

const resolveErrorBannerText = (message: ChatMessage): string => {
  const normalizedErrorCode =
    typeof message.errorCode === "string" ? message.errorCode.trim() : "";

  if (AGENT_CONNECTIVITY_ERROR_CODES.has(normalizedErrorCode)) {
    return "当前无法连接到上游 Agent，请稍后重试。";
  }

  if (normalizedErrorCode === "outbound_not_allowed") {
    return "当前配置不允许访问该上游 Agent。";
  }

  if (STREAM_FAILURE_ERROR_CODES.has(normalizedErrorCode)) {
    return "流响应异常，请重试。";
  }

  if (typeof message.errorMessage === "string" && message.errorMessage.trim()) {
    return message.errorMessage.trim();
  }

  return "流响应异常，请重试。";
};

export function ChatMessageItem({
  message,
  isLastMessage,
  sessionStreamState,
  onLayoutChangeStart,
  onLoadBlockContent,
  onRetry,
}: {
  message: ChatMessage;
  index: number;
  isLastMessage: boolean;
  sessionStreamState?: string | null;
  onLayoutChangeStart?: () => void;
  onLoadBlockContent?: (messageId: string, blockId: string) => Promise<boolean>;
  onRetry: () => void;
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
    const normalizedContent = message.content.trim();
    if (normalizedContent) {
      return normalizedContent;
    }

    if (message.role !== "agent" || !message.blocks?.length) {
      return "";
    }

    return message.blocks
      .map((block) => block.content.trim())
      .filter(Boolean)
      .join("\n\n")
      .trim();
  }, [message.blocks, message.content, message.role]);

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
      className={`mb-4 flex ${
        message.role === "user" ? "items-end" : "items-start"
      }`}
    >
      <View className="max-w-[94%] relative group">
        <Pressable
          onLongPress={canCopyMessage ? handleLongPressCopy : undefined}
          delayLongPress={500}
          className={`px-4 py-3 rounded-2xl shadow-sm ${
            message.role === "user"
              ? "bg-[#1E222D]"
              : message.role === "agent"
                ? "bg-surface"
                : "bg-slate-900"
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
    </View>
  );
}
