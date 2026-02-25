import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useCallback, useMemo, useState } from "react";
import { Platform, Pressable, Text, View } from "react-native";

import { CopyButton } from "../ui/CopyButton";

import { ChatMessage, MessageBlock } from "@/lib/api/chat-utils";
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
      await handleCopyPayload(textToCopy);
      toast.success("Copied", "Message copied to clipboard.");
    } catch {
      toast.error("Copy failed", "Could not copy message.");
    }
  }, [handleCopyPayload, textToCopy]);

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
          className="rounded-md px-2 py-1"
          accessibilityRole="button"
          accessibilityLabel="Collapse full text"
          testID={testId}
          onPress={onPress}
        >
          <Text className="text-xs font-semibold text-slate-300">
            Show less
          </Text>
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
          className={`px-4 py-3 ${
            message.role === "user"
              ? "rounded-2xl rounded-tr-sm bg-primary"
              : message.role === "agent"
                ? "rounded-2xl rounded-tl-sm bg-slate-800"
                : "rounded-2xl bg-slate-900"
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
                    } rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2`}
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
                      <Text className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                        {expanded ? "Hide Reasoning" : "Show Reasoning"}
                      </Text>
                    </Pressable>
                    {expanded ? (
                      <View>
                        <Text
                          selectable
                          className="mt-1 break-all text-xs text-slate-300"
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
                    } rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2`}
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
                      <Text className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                        {expanded ? "Hide Tool Call" : "Show Tool Call"}
                      </Text>
                    </Pressable>
                    {expanded ? (
                      <View>
                        <Text
                          selectable
                          className="mt-1 break-all text-xs text-slate-300"
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
                  <View key={blockId} className="rounded-xl">
                    <Text
                      selectable
                      className={`${
                        blockIndex > 0 ? "mt-3" : ""
                      } break-all text-sm text-white`}
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
                        className="mt-2 rounded-md px-2 py-1"
                        accessibilityRole="button"
                        accessibilityLabel={topToggleAccessibilityLabel}
                        testID={`chat-message-${blockId}-expand`}
                        onPress={() => toggleTextExpansion(blockId)}
                      >
                        <Text className="text-xs font-semibold text-slate-300">
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
                  } rounded-xl border border-slate-700/70 bg-slate-900/70 px-3 py-2`}
                >
                  <Text className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                    {block.type}
                  </Text>
                  <Text
                    selectable
                    className="mt-1 break-all text-xs text-slate-300"
                  >
                    {blockText}
                  </Text>
                </View>
              );
            })
          ) : (
            <View className="rounded-xl">
              <Text
                selectable
                className="break-all text-sm text-white"
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
                  className="mt-2 rounded-md px-2 py-1"
                  accessibilityRole="button"
                  accessibilityLabel={plainTopToggleAccessibilityLabel}
                  testID={`chat-message-${message.id}-expand`}
                  onPress={() => toggleTextExpansion(message.id)}
                >
                  <Text className="text-xs font-semibold text-slate-300">
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
            <Text className="mt-1 text-[10px] text-muted">Streaming...</Text>
          ) : null}
        </Pressable>
        <CopyButton
          value={textToCopy}
          variant="ghost"
          size="xs"
          className={`absolute bottom-2 ${userCopyButtonPositionClass} opacity-45`}
          accessibilityLabel="Copy message"
          successMessage="Message copied to clipboard."
          idleIcon="copy-outline"
          copiedIcon="checkmark"
          iconColor={message.role === "user" ? "#ffffff" : "#cbd5e1"}
        />
      </View>
      {canRetry && (
        <Pressable
          onPress={onRetry}
          className="mt-1.5 flex-row items-center gap-1 opacity-70"
        >
          <Ionicons name="refresh" size={12} color="#94a3b8" />
          <Text className="text-[10px] font-semibold text-slate-400">
            Retry
          </Text>
        </Pressable>
      )}
    </View>
  );
}
