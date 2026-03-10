import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useCallback } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  Text,
  View,
} from "react-native";

import { GenericBlock } from "./blocks/GenericBlock";
import { ReasoningBlock } from "./blocks/ReasoningBlock";
import { TextBlock } from "./blocks/TextBlock";
import { ToolCallBlock } from "./blocks/ToolCallBlock";

import { type ChatMessage, type MessageBlock } from "@/lib/api/chat-utils";
import { toast } from "@/lib/toast";

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
    (msg: ChatMessage): MessageBlock[] => {
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

  const handleCopyPayload = useCallback(async (text: string) => {
    if (Platform.OS === "web" && typeof navigator !== "undefined") {
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(text);
          return;
        } catch {
          // Fall back to Expo clipboard API when browser clipboard write is blocked.
        }
      }
    }
    await Clipboard.setStringAsync(text);
  }, []);

  const handleCopyMessage = useCallback(async () => {
    try {
      let textToCopy = message.content;
      if (message.role === "agent" && message.blocks?.length) {
        const blockContent = message.blocks
          .map((b) => `[${b.type}]\n${b.content}`)
          .join("\n\n");
        if (blockContent) {
          textToCopy = `${blockContent}\n\n${textToCopy}`;
        }
      }
      await handleCopyPayload(textToCopy.trim());
      toast.success("Copied", "Message copied to clipboard.");
    } catch {
      toast.error("Copy failed", "Could not copy message.");
    }
  }, [handleCopyPayload, message]);

  const renderableBlocks = deriveRenderableBlocks(message);
  const hasBlocks = message.role === "agent" && renderableBlocks.length > 0;
  const hasPlainContent = message.content.trim().length > 0;
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
      <View className="max-w-[94%] relative">
        <Pressable
          onLongPress={handleCopyMessage}
          delayLongPress={500}
          className={`px-4 py-3 rounded-2xl shadow-sm ${
            message.role === "user"
              ? "bg-[#1E222D]"
              : message.role === "agent"
                ? "bg-surface"
                : "bg-slate-900"
          }`}
        >
          {hasBlocks ? (
            renderableBlocks.map((block, blockIndex) => {
              const blockId = block.id || `${message.id}:${blockIndex}`;
              const isFirst = blockIndex === 0;

              switch (block.type) {
                case "reasoning":
                  return (
                    <ReasoningBlock
                      key={blockId}
                      block={block}
                      fallbackBlockId={blockId}
                      messageId={message.id}
                      onLayoutChangeStart={onLayoutChangeStart}
                      onLoadBlockContent={onLoadBlockContent}
                      isFirst={isFirst}
                    />
                  );
                case "tool_call":
                  return (
                    <ToolCallBlock
                      key={blockId}
                      block={block}
                      fallbackBlockId={blockId}
                      messageId={message.id}
                      onLayoutChangeStart={onLayoutChangeStart}
                      onLoadBlockContent={onLoadBlockContent}
                      isFirst={isFirst}
                    />
                  );
                case "text":
                  return (
                    <TextBlock
                      key={blockId}
                      block={block}
                      fallbackBlockId={blockId}
                      isAgent={message.role === "agent"}
                      isFirst={isFirst}
                    />
                  );
                default:
                  return (
                    <GenericBlock
                      key={blockId}
                      block={block}
                      fallbackBlockId={blockId}
                      isFirst={isFirst}
                    />
                  );
              }
            })
          ) : (
            <View>
              {hasPlainContent ? (
                <TextBlock
                  content={message.content}
                  fallbackBlockId={message.id}
                  isAgent={message.role === "agent"}
                  isFirst
                />
              ) : (
                <View className="rounded-lg bg-black/20 px-3 py-2">
                  <Text className="text-[11px] font-medium text-slate-400">
                    Content unavailable.
                  </Text>
                </View>
              )}
            </View>
          )}
          {message.status === "streaming" ? (
            <View className="mt-2 flex-row items-center gap-2">
              <ActivityIndicator size="small" color="#34D399" />
              <Text className="text-[11px] font-medium italic text-neo-green/60">
                Streaming...
              </Text>
            </View>
          ) : null}
        </Pressable>
        <Pressable
          className={`absolute bottom-2 ${userCopyButtonPositionClass} rounded-lg px-2 py-2 opacity-30`}
          onPress={handleCopyMessage}
          accessibilityRole="button"
          accessibilityLabel="Copy message"
        >
          <Ionicons name="copy-outline" size={16} color="#FFFFFF" />
        </Pressable>
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
