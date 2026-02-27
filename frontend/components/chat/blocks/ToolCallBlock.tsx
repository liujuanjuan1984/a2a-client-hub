import React, { useCallback, useState } from "react";
import { Text, View } from "react-native";

import { ExpandToggle } from "@/components/ui/ExpandToggle";
import { type MessageBlock } from "@/lib/api/chat-utils";

interface ToolCallBlockProps {
  block: MessageBlock;
  fallbackBlockId: string;
  messageId: string;
  onLayoutChangeStart?: () => void;
  onLoadBlockContent?: (messageId: string, blockId: string) => Promise<boolean>;
  isFirst?: boolean;
}

export function ToolCallBlock({
  block,
  fallbackBlockId,
  messageId,
  onLayoutChangeStart,
  onLoadBlockContent,
  isFirst,
}: ToolCallBlockProps) {
  const [expanded, setExpanded] = useState(false);

  const blockText = block.content;
  const blockHasContent = blockText.length > 0;
  const blockId = block.id || fallbackBlockId;

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

  return (
    <View
      key={blockId}
      className={`${!isFirst ? "mt-3" : ""} rounded-xl bg-black/40 p-3`}
    >
      <ExpandToggle
        expanded={expanded}
        onToggle={() => {
          handleToggle().catch(() => undefined);
        }}
        type="Tool Call"
        showChevron={false}
      />

      {expanded && blockHasContent ? (
        <View>
          <Text
            selectable
            className="mt-2 break-all text-[11px] leading-5 text-slate-400 font-normal"
          >
            {blockText}
          </Text>
          <View className="mt-2 items-end">
            <ExpandToggle
              expanded
              onToggle={toggleToolCall}
              testID={`chat-message-${blockId}-collapse-bottom`}
              showChevron={false}
            />
          </View>
        </View>
      ) : null}
    </View>
  );
}
