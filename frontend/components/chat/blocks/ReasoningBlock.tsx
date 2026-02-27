import React, { useCallback, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { type MessageBlock } from "@/lib/api/chat-utils";

interface ReasoningBlockProps {
  block: MessageBlock;
  messageId: string;
  onLayoutChangeStart?: () => void;
  onLoadBlockContent?: (messageId: string, blockId: string) => Promise<boolean>;
  isFirst?: boolean;
}

export function ReasoningBlock({
  block,
  messageId,
  onLayoutChangeStart,
  onLoadBlockContent,
  isFirst,
}: ReasoningBlockProps) {
  const [expanded, setExpanded] = useState(false);

  const blockText = block.content;
  const blockHasContent = blockText.length > 0;
  const blockId = block.id || `${messageId}:reasoning`;

  const toggleReasoning = useCallback(() => {
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
    toggleReasoning();
  };

  const renderBottomCollapseAction = () => {
    return (
      <View className="mt-2 items-end">
        <Pressable
          className="rounded-lg bg-black/20 px-2.5 py-1"
          accessibilityRole="button"
          accessibilityLabel="Collapse full text"
          testID={`chat-message-${blockId}-collapse-bottom`}
          onPress={toggleReasoning}
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
          expanded ? "Hide reasoning details" : "Show reasoning details"
        }
      >
        <View className="flex-row items-center gap-1.5">
          <View className="h-1 w-1 rounded-full bg-slate-600" />
          <Text className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {expanded ? "Hide Reasoning" : "Show Reasoning"}
          </Text>
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
