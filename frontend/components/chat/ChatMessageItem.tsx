import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useMemo } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { MessageBlock, MessageContentFallback } from "./MessageBlock";
import { CopyButton } from "../ui/CopyButton";

import {
  type ChatMessage,
  type MessageBlock as MessageBlockType,
} from "@/lib/api/chat-utils";

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
    let text = message.content;
    if (message.role === "agent" && message.blocks?.length) {
      const blockContent = message.blocks
        .map((b) => `[${b.type}]\n${b.content}`)
        .join("\n\n");
      if (blockContent) {
        text = `${blockContent}\n\n${text}`;
      }
    }
    return text.trim();
  }, [message]);

  const renderableBlocks = deriveRenderableBlocks(message);
  const hasBlocks = message.role === "agent" && renderableBlocks.length > 0;
  const hasPlainContent = message.content.trim().length > 0;
  const suppressFallbackWhileStreaming =
    message.role === "agent" &&
    message.status === "streaming" &&
    !hasBlocks &&
    !hasPlainContent;
  const canRetry =
    isLastMessage &&
    message.role === "agent" &&
    sessionStreamState &&
    ["error", "recoverable"].includes(sessionStreamState);
  const userCopyButtonPositionClass = "right-0";

  return (
    <View
      className={`mb-4 flex ${
        message.role === "user" ? "items-end" : "items-start"
      }`}
    >
      <View className="max-w-[94%] relative group">
        <View
          className={`px-4 py-3 rounded-2xl shadow-sm ${
            message.role === "user"
              ? "bg-[#1E222D]"
              : message.role === "agent"
                ? "bg-surface"
                : "bg-slate-900"
          }`}
        >
          {hasBlocks
            ? renderableBlocks.map((block, blockIndex) => (
                <MessageBlock
                  key={block.id || `${message.id}:${blockIndex}`}
                  block={block}
                  messageId={message.id}
                  blockIndex={blockIndex}
                  role={message.role}
                  onLayoutChangeStart={onLayoutChangeStart}
                  onLoadBlockContent={onLoadBlockContent}
                />
              ))
            : !suppressFallbackWhileStreaming && (
                <MessageContentFallback
                  hasPlainContent={hasPlainContent}
                  content={message.content}
                  messageId={message.id}
                  role={message.role}
                />
              )}
          {message.status === "streaming" ? (
            <View className="mt-2 flex-row items-center gap-2">
              <ActivityIndicator size="small" color="#34D399" />
              <Text className="text-[11px] font-medium italic text-neo-green/60">
                Streaming...
              </Text>
            </View>
          ) : null}
        </View>
        <View
          className={`absolute bottom-1 ${userCopyButtonPositionClass} opacity-30`}
        >
          <CopyButton
            value={textToCopy}
            successMessage="Message copied to clipboard."
            accessibilityLabel="Copy message"
            variant="ghost"
            size="sm"
            icon="copy-outline"
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
