import React from "react";
import { View } from "react-native";

import { MarkdownRender } from "../MarkdownRender";

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
    <View key={blockId} className={!isFirst ? "mt-3" : ""}>
      <MarkdownRender content={blockText} isAgent={isAgent} />
    </View>
  );
}
