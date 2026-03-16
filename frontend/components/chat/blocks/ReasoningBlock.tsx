import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { CopyButton } from "@/components/ui/CopyButton";
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

function summarizeReasoning(content: string) {
  const firstParagraph = content.trim().split(/\n\s*\n/)[0] ?? "";
  return {
    preview:
      firstParagraph.slice(0, 140) + (firstParagraph.length > 140 ? "..." : ""),
    length: content.length,
  };
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

  const blockText = block.content;
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

  const summary = summarizeReasoning(blockText);

  return (
    <View
      key={blockId}
      className={`${!isFirst ? "mt-3" : ""} rounded-xl border border-slate-700/50 bg-slate-800/30 overflow-hidden`}
    >
      <View className="flex-row items-center justify-between px-3 py-2 bg-slate-800/50">
        <View className="flex-row items-center space-x-2">
          <Ionicons name="git-network-outline" size={14} color="#94a3b8" />
          <Text className="text-[12px] font-medium text-slate-300 ml-1.5">
            Reasoning Process
          </Text>
        </View>
        <ExpandToggle
          expanded={expanded}
          onToggle={() => {
            handleToggle().catch(() => undefined);
          }}
          type=""
          label={expanded ? "Hide" : "Show"}
          variant="mini"
          showChevron
        />
      </View>

      {blockHasContent ? (
        <View className="px-3 pb-3">
          {expanded ? (
            <View className="mt-2">
              <ScrollView nestedScrollEnabled className="max-h-96">
                <Text
                  selectable
                  className="text-[13px] leading-5 text-slate-300 font-normal break-all"
                >
                  {blockText}
                </Text>
              </ScrollView>
              <View className="mt-3 flex-row justify-between items-center border-t border-slate-700/50 pt-2">
                <View className="flex-row items-center gap-2">
                  <Text className="text-[10px] text-slate-500">
                    {summary.length} chars
                  </Text>
                  <CopyButton
                    value={blockText}
                    successMessage="Reasoning process copied."
                    errorMessage="Failed to copy reasoning process."
                    accessibilityLabel="Copy reasoning process"
                    variant="ghost"
                    size="sm"
                    iconColor="#94a3b8"
                  />
                </View>
                <ExpandToggle
                  expanded
                  onToggle={toggleReasoning}
                  testID={`chat-message-${blockId}-collapse-bottom`}
                  variant="mini"
                  label="Collapse"
                  showChevron
                />
              </View>
            </View>
          ) : (
            <Text
              className="mt-2 text-[12px] leading-4 text-slate-400 italic"
              numberOfLines={2}
            >
              {summary.preview || "Thinking..."}
            </Text>
          )}
        </View>
      ) : (
        <View className="px-3 pb-3">
          <Text className="mt-2 text-[12px] leading-4 text-slate-500 italic">
            Loading reasoning process...
          </Text>
        </View>
      )}
    </View>
  );
}
