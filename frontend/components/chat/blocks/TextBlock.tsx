import React from "react";
import { Text, View } from "react-native";

import { type MessageBlock } from "@/lib/api/chat-utils";

interface TextBlockProps {
  block?: MessageBlock;
  content?: string;
  fallbackBlockId: string;
  isAgent: boolean;
  isFirst?: boolean;
}

export function TextBlock({
  block,
  content,
  fallbackBlockId,
  isAgent,
  isFirst,
}: TextBlockProps) {
  const blockText = (block?.content ?? content ?? "").trim();
  const blockId = block?.id ?? fallbackBlockId;

  if (!blockText) {
    return null;
  }

  return (
    <View key={blockId}>
      <Text
        selectable
        className={`${
          !isFirst ? "mt-3" : ""
        } break-all text-sm leading-6 font-normal ${
          isAgent ? "text-slate-200" : "text-white"
        }`}
      >
        {blockText}
      </Text>
    </View>
  );
}
