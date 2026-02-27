import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { type MessageBlock } from "@/lib/api/chat-utils";

interface ToolCallBlockProps {
  block: MessageBlock;
  messageId: string;
  onLayoutChangeStart?: () => void;
  onLoadBlockContent?: (messageId: string, blockId: string) => Promise<boolean>;
  isFirst?: boolean;
}

export function ToolCallBlock({
  block,
  messageId,
  onLayoutChangeStart,
  onLoadBlockContent,
  isFirst,
}: ToolCallBlockProps) {
  const [expanded, setExpanded] = useState(false);

  const blockText = block.content;
  const blockHasContent = blockText.length > 0;
  const blockId = block.id || `${messageId}:tool_call`;

  const toggleToolCall = useCallback(() => {
    onLayoutChangeStart?.();
    setExpanded((prev) => !prev);
  }, [onLayoutChangeStart]);

  const handleToggle = async () => {
    const shouldExpand = !expanded;
    if (shouldExpand && !blockHasContent && onLoadBlockContent) {
      const loaded = await onLoadBlockContent(messageId, blockId);
      if (!loaded) {
        return;
      }
    }
    toggleToolCall();
  };

  const renderBottomCollapseAction = () => {
    return (
      <View className="mt-2 items-end">
        <Pressable
          className="rounded-lg bg-black/20 px-2.5 py-1"
          accessibilityRole="button"
          accessibilityLabel="Collapse full text"
          testID={`chat-message-${blockId}-collapse-bottom`}
          onPress={toggleToolCall}
        >
          <Text className="text-[11px] font-medium text-slate-500">
            Show less
          </Text>
        </Pressable>
      </View>
    );
  };

  return (
    <View
      key={blockId}
      className={`${!isFirst ? "mt-3" : ""} rounded-xl bg-black/40 p-3`}
    >
      <Pressable
        onPress={() => {
          handleToggle().catch(() => undefined);
        }}
        accessibilityRole="button"
        accessibilityLabel={
          expanded ? "Hide tool call details" : "Show tool call details"
        }
      >
        <View className="flex-row items-center justify-between">
          <View className="flex-row items-center gap-1.5">
            <Ionicons name="construct" size={10} color="#64748B" />
            <Text className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
              {expanded ? "Hide Tool Call" : "Show Tool Call"}
            </Text>
          </View>
        </View>
      </Pressable>

      {expanded && blockHasContent ? (
        <View>
          <Text
            selectable
            className="mt-2 break-all text-[11px] leading-5 text-slate-400 font-normal"
          >
            {blockText}
          </Text>
          {renderBottomCollapseAction()}
        </View>
      ) : null}
    </View>
  );
}
