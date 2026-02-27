import React, { useCallback, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { type MessageBlock } from "@/lib/api/chat-utils";
import { COLLAPSED_TEXT_LINES, shouldCollapseByLength } from "@/lib/chat-utils";

interface TextBlockProps {
  block?: MessageBlock;
  content?: string;
  fallbackBlockId: string;
  isAgent: boolean;
  onLayoutChangeStart?: () => void;
  isFirst?: boolean;
}

export function TextBlock({
  block,
  content,
  fallbackBlockId,
  isAgent,
  onLayoutChangeStart,
  isFirst,
}: TextBlockProps) {
  const [expanded, setExpanded] = useState(false);

  const blockText = block?.content ?? content ?? "";
  const blockId = block?.id ?? fallbackBlockId;

  const toggleTextExpansion = useCallback(() => {
    onLayoutChangeStart?.();
    setExpanded((prev) => !prev);
  }, [onLayoutChangeStart]);

  if (!blockText.trim()) {
    return null;
  }

  const shouldCollapse = shouldCollapseByLength(blockText);
  const topToggleAccessibilityLabel = expanded
    ? "Collapse full text"
    : "Expand full text";
  const topToggleLabel = expanded ? "Show less" : "Read more";

  const renderBottomCollapseAction = () => {
    return (
      <View className="mt-2 items-end">
        <Pressable
          className="rounded-lg bg-black/20 px-2.5 py-1"
          accessibilityRole="button"
          accessibilityLabel="Collapse full text"
          testID={`chat-message-${blockId}-collapse-bottom`}
          onPress={toggleTextExpansion}
        >
          <Text className="text-[11px] font-medium text-slate-500">
            Show less
          </Text>
        </Pressable>
      </View>
    );
  };

  return (
    <View key={blockId}>
      <Text
        selectable
        className={`${
          !isFirst ? "mt-3" : ""
        } break-all text-sm leading-6 font-normal ${
          isAgent ? "text-slate-200" : "text-white"
        }`}
        numberOfLines={
          shouldCollapse && !expanded ? COLLAPSED_TEXT_LINES : undefined
        }
      >
        {blockText}
      </Text>
      {shouldCollapse ? (
        <Pressable
          className="mt-2 rounded-lg bg-black/20 px-2.5 py-1"
          accessibilityRole="button"
          accessibilityLabel={topToggleAccessibilityLabel}
          testID={`chat-message-${blockId}-expand`}
          onPress={toggleTextExpansion}
        >
          <Text className="text-[11px] font-medium text-slate-500">
            {topToggleLabel}
          </Text>
        </Pressable>
      ) : null}
      {shouldCollapse && expanded ? renderBottomCollapseAction() : null}
    </View>
  );
}
