import React from "react";
import { Text, View } from "react-native";

import { type MessageBlock } from "@/lib/api/chat-utils";

interface DataBlockProps {
  block: MessageBlock;
  fallbackBlockId: string;
  isFirst?: boolean;
}

const formatStructuredContent = (content: string): string => {
  const trimmed = content.trim();
  if (!trimmed) {
    return "";
  }
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return content;
  }
};

export function DataBlock({ block, fallbackBlockId, isFirst }: DataBlockProps) {
  const blockId = block.id || fallbackBlockId;
  const renderedContent = formatStructuredContent(block.content);

  return (
    <View
      key={blockId}
      className={`${!isFirst ? "mt-3" : ""} rounded-xl border border-slate-700 bg-slate-950/70 p-3`}
    >
      <Text className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        Structured result
      </Text>
      <Text
        selectable
        className="mt-2 font-mono text-[11px] leading-5 text-slate-200"
      >
        {renderedContent || "{}"}
      </Text>
    </View>
  );
}
