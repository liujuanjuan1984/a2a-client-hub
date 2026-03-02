import React, { useCallback, useState } from "react";
import { Text, View } from "react-native";

import { ExpandToggle } from "@/components/ui/ExpandToggle";
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

  const blockText = (block?.content ?? content ?? "").trim();
  const blockId = block?.id ?? fallbackBlockId;

  const toggleTextExpansion = useCallback(() => {
    onLayoutChangeStart?.();
    setExpanded((prev) => !prev);
  }, [onLayoutChangeStart]);

  if (!blockText) {
    return null;
  }

  const shouldCollapse = shouldCollapseByLength(blockText);
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
      {shouldCollapse && !expanded ? (
        <View className="mt-2">
          <ExpandToggle
            expanded={false}
            onToggle={toggleTextExpansion}
            testID={`chat-message-${blockId}-expand`}
            showChevron={false}
          />
        </View>
      ) : null}
      {shouldCollapse && expanded ? (
        <View className="mt-2 items-end">
          <ExpandToggle
            expanded
            onToggle={toggleTextExpansion}
            testID={`chat-message-${blockId}-collapse-bottom`}
            showChevron={false}
          />
        </View>
      ) : null}
    </View>
  );
}
