import React from "react";
import { Text, View } from "react-native";

import { type MessageBlock } from "@/lib/api/chat-utils";

interface InterruptEventBlockProps {
  block: MessageBlock;
  fallbackBlockId: string;
  isFirst?: boolean;
}

export function InterruptEventBlock({
  block,
  fallbackBlockId,
  isFirst,
}: InterruptEventBlockProps) {
  const blockText = block.content.trim();
  const blockId = block.id || fallbackBlockId;

  if (!blockText) {
    return null;
  }

  return (
    <View
      key={blockId}
      className={`${!isFirst ? "mt-3" : ""} rounded-xl border border-amber-500/30 bg-amber-500/10 p-3`}
    >
      <Text className="text-[11px] font-medium uppercase tracking-wide text-amber-200">
        Interrupt
      </Text>
      <Text
        selectable
        className="mt-2 text-[12px] leading-5 text-amber-50 font-normal"
      >
        {blockText}
      </Text>
    </View>
  );
}
