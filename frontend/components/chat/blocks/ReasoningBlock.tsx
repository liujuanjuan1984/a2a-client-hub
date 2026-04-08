import React, { useCallback, useState } from "react";
import { View } from "react-native";

import { LazyMarkdownRender } from "../LazyMarkdownRender";

import { ExpandToggle } from "@/components/ui/ExpandToggle";
import { type MessageBlock } from "@/lib/api/chat-utils";

interface ReasoningBlockProps {
  block: MessageBlock;
  fallbackBlockId: string;
  messageId: string;
  onLayoutChangeStart?: () => void;
  onLoadBlockContent?: (messageId: string, blockId: string) => Promise<boolean>;
  isFirst?: boolean;
}

export function ReasoningBlock({
  block,
  fallbackBlockId,
  messageId,
  onLayoutChangeStart,
  onLoadBlockContent,
  isFirst,
}: ReasoningBlockProps) {
  const [expanded, setExpanded] = useState(false);

  const blockText = block.content.trim();
  const blockHasContent = blockText.length > 0;
  const blockId = block.id || fallbackBlockId;

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

  return (
    <View
      key={blockId}
      className={`${!isFirst ? "mt-3" : ""} rounded-xl bg-black/40 p-3`}
    >
      {!(expanded && blockHasContent) ? (
        <ExpandToggle
          expanded={expanded}
          onToggle={() => {
            handleToggle().catch(() => undefined);
          }}
          type="Reasoning"
          showChevron={false}
        />
      ) : null}
      {expanded && blockHasContent ? (
        <View>
          <View className="mt-2">
            <LazyMarkdownRender content={blockText} isAgent />
          </View>
          <View className="mt-1 items-end">
            <ExpandToggle
              expanded
              onToggle={toggleReasoning}
              testID={`chat-message-${blockId}-collapse-bottom`}
              variant="mini"
              showChevron
            />
          </View>
        </View>
      ) : null}
    </View>
  );
}
