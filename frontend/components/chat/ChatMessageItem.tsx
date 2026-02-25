import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useCallback, useState } from "react";
import { Platform, Pressable, Text, View } from "react-native";

import { type ChatMessage, type MessageBlock } from "@/lib/api/chat-utils";
import { COLLAPSED_TEXT_LINES, shouldCollapseByLength } from "@/lib/chat-utils";
import { toast } from "@/lib/toast";

export function ChatMessageItem({
  message,
  index,
  isLastMessage,
  sessionStreamState,
  onLayoutChangeStart,
  onRetry,
}: {
  message: ChatMessage;
  index: number;
  isLastMessage: boolean;
  sessionStreamState?: string | null;
  onLayoutChangeStart?: () => void;
  onRetry: () => void;
}) {
  const [expandedReasoningByBlockId, setExpandedReasoningByBlockId] = useState<
    Record<string, boolean>
  >({});
  const [expandedToolCallByBlockId, setExpandedToolCallByBlockId] = useState<
    Record<string, boolean>
  >({});
  const [expandedTextByBlockId, setExpandedTextByBlockId] = useState<
    Record<string, boolean>
  >({});

  const toggleReasoning = useCallback(
    (blockId: string) => {
      onLayoutChangeStart?.();
      setExpandedReasoningByBlockId((current) => ({
        ...current,
        [blockId]: !current[blockId],
      }));
    },
    [onLayoutChangeStart],
  );

  const toggleToolCall = useCallback(
    (blockId: string) => {
      onLayoutChangeStart?.();
      setExpandedToolCallByBlockId((current) => ({
        ...current,
        [blockId]: !current[blockId],
      }));
    },
    [onLayoutChangeStart],
  );

  const toggleTextExpansion = useCallback(
    (blockId: string) => {
      onLayoutChangeStart?.();
      setExpandedTextByBlockId((current) => ({
        ...current,
        [blockId]: !current[blockId],
      }));
    },
    [onLayoutChangeStart],
  );

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
  const plainTextExpanded = expandedTextByBlockId[message.id] ?? false;
  const plainShouldCollapse = shouldCollapseByLength(message.content);
  const plainTopToggleAccessibilityLabel = plainTextExpanded
    ? "Collapse full text"
    : "Expand full text";
  const plainTopToggleLabel = plainTextExpanded ? "Show less" : "Read more";
  const canRetry =
    isLastMessage &&
    message.role === "agent" &&
    sessionStreamState &&
    ["error", "recoverable"].includes(sessionStreamState);
  const userCopyButtonPositionClass = "right-0";
  const renderBottomCollapseAction = (testId: string, onPress: () => void) => {
    return (
      <View className="mt-2 items-end">
        <Pressable
          className="border border-white bg-surface px-2 py-1"
          accessibilityRole="button"
          accessibilityLabel="Collapse full text"
          testID={testId}
          onPress={onPress}
        >
          <Text className="text-xs font-bold text-white">Show less</Text>
        </Pressable>
      </View>
    );
  };

  return (
    <View
      className={`mb-3 flex ${
        message.role === "user" ? "items-end" : "items-start"
      }`}
    >
      <View className="max-w-[94%] relative">
        <Pressable
          onLongPress={handleCopyMessage}
          delayLongPress={500}
          className={`px-4 py-3 border-neo border-white shadow-neo ${
            message.role === "user"
              ? "bg-neo-yellow"
              : message.role === "agent"
                ? "bg-surface"
                : "bg-gray-800"
          }`}
        >
          {hasBlocks ? (
            renderableBlocks.map((block, blockIndex) => {
              const blockText = block.content;
              if (blockText.length === 0) return null;
              const blockId = block.id || `${message.id}:${blockIndex}`;
              if (block.type === "reasoning") {
                const expanded = expandedReasoningByBlockId[blockId];
                return (
                  <View
                    key={blockId}
                    className={`${
                      blockIndex > 0 ? "mt-3" : ""
                    } border-2 border-white bg-black/40 px-3 py-2`}
                  >
                    <Pressable
                      onPress={() => toggleReasoning(blockId)}
                      accessibilityRole="button"
                      accessibilityLabel={
                        expanded
                          ? "Hide reasoning details"
                          : "Show reasoning details"
                      }
                    >
                      <Text className="text-[10px] font-bold uppercase tracking-wide text-white">
                        {expanded ? "Hide Reasoning" : "Show Reasoning"}
                      </Text>
                    </Pressable>
                    {expanded ? (
                      <View>
                        <Text
                          selectable
                          className="mt-1 break-all text-xs text-white"
                        >
                          {blockText}
                        </Text>
                        {renderBottomCollapseAction(
                          `chat-message-${blockId}-collapse-bottom`,
                          () => toggleReasoning(blockId),
                        )}
                      </View>
                    ) : null}
                  </View>
                );
              }
              if (block.type === "tool_call") {
                const expanded = expandedToolCallByBlockId[blockId];
                return (
                  <View
                    key={blockId}
                    className={`${
                      blockIndex > 0 ? "mt-3" : ""
                    } border-2 border-white bg-black/40 px-3 py-2`}
                  >
                    <Pressable
                      onPress={() => toggleToolCall(blockId)}
                      accessibilityRole="button"
                      accessibilityLabel={
                        expanded
                          ? "Hide tool call details"
                          : "Show tool call details"
                      }
                    >
                      <Text className="text-[10px] font-bold uppercase tracking-wide text-white">
                        {expanded ? "Hide Tool Call" : "Show Tool Call"}
                      </Text>
                    </Pressable>
                    {expanded ? (
                      <View>
                        <Text
                          selectable
                          className="mt-1 break-all text-xs text-white"
                        >
                          {blockText}
                        </Text>
                        {renderBottomCollapseAction(
                          `chat-message-${blockId}-collapse-bottom`,
                          () => toggleToolCall(blockId),
                        )}
                      </View>
                    ) : null}
                  </View>
                );
              }
              if (block.type === "text") {
                const blockExpanded = expandedTextByBlockId[blockId] ?? false;
                const shouldCollapse = shouldCollapseByLength(blockText);
                const topToggleAccessibilityLabel = blockExpanded
                  ? "Collapse full text"
                  : "Expand full text";
                const topToggleLabel = blockExpanded
                  ? "Show less"
                  : "Read more";

                return (
                  <View key={blockId}>
                    <Text
                      selectable
                      className={`${
                        blockIndex > 0 ? "mt-3" : ""
                      } break-all text-sm ${message.role === "user" ? "text-black" : "text-white"}`}
                      numberOfLines={
                        shouldCollapse && !blockExpanded
                          ? COLLAPSED_TEXT_LINES
                          : undefined
                      }
                    >
                      {blockText}
                    </Text>
                    {shouldCollapse ? (
                      <Pressable
                        className="mt-2 border border-white bg-surface px-2 py-1"
                        accessibilityRole="button"
                        accessibilityLabel={topToggleAccessibilityLabel}
                        testID={`chat-message-${blockId}-expand`}
                        onPress={() => toggleTextExpansion(blockId)}
                      >
                        <Text className="text-xs font-bold text-white">
                          {topToggleLabel}
                        </Text>
                      </Pressable>
                    ) : null}
                    {shouldCollapse && blockExpanded
                      ? renderBottomCollapseAction(
                          `chat-message-${blockId}-collapse-bottom`,
                          () => toggleTextExpansion(blockId),
                        )
                      : null}
                  </View>
                );
              }
              return (
                <View
                  key={blockId}
                  className={`${
                    blockIndex > 0 ? "mt-3" : ""
                  } border-2 border-white bg-black/40 px-3 py-2`}
                >
                  <Text className="text-[10px] font-bold uppercase tracking-wide text-white">
                    {block.type}
                  </Text>
                  <Text
                    selectable
                    className="mt-1 break-all text-xs text-white"
                  >
                    {blockText}
                  </Text>
                </View>
              );
            })
          ) : (
            <View>
              <Text
                selectable
                className={`break-all text-sm ${message.role === "user" ? "text-black" : "text-white"}`}
                numberOfLines={
                  plainShouldCollapse && !plainTextExpanded
                    ? COLLAPSED_TEXT_LINES
                    : undefined
                }
              >
                {message.content}
              </Text>
              {plainShouldCollapse ? (
                <Pressable
                  className="mt-2 border border-white bg-surface px-2 py-1"
                  accessibilityRole="button"
                  accessibilityLabel={plainTopToggleAccessibilityLabel}
                  testID={`chat-message-${message.id}-expand`}
                  onPress={() => toggleTextExpansion(message.id)}
                >
                  <Text className="text-xs font-bold text-white">
                    {plainTopToggleLabel}
                  </Text>
                </Pressable>
              ) : null}
              {plainShouldCollapse && plainTextExpanded
                ? renderBottomCollapseAction(
                    `chat-message-${message.id}-collapse-bottom`,
                    () => toggleTextExpansion(message.id),
                  )
                : null}
            </View>
          )}
          {message.status === "streaming" ? (
            <Text className={`mt-1 text-[10px] font-bold italic ${message.role === "user" ? "text-black" : "text-white"}`}>
              Streaming...
            </Text>
          ) : null}
        </Pressable>
        <Pressable
          className={`absolute bottom-2 ${userCopyButtonPositionClass} rounded-lg px-2 py-2 opacity-45`}
          onPress={handleCopyMessage}
          accessibilityRole="button"
          accessibilityLabel="Copy message"
        >
          <Ionicons name="copy-outline" size={16} color={message.role === "user" ? "#000000" : "#FFFFFF"} />
        </Pressable>
      </View>
      {canRetry && (
        <Pressable
          onPress={onRetry}
          className="mt-1.5 flex-row items-center gap-1 opacity-70"
        >
          <Ionicons name="refresh" size={12} color="#FFFFFF" />
          <Text className="text-[10px] font-bold text-white">
            Retry
          </Text>
        </Pressable>
      )}
    </View>
  );
}
