import React from "react";
import { Text, View } from "react-native";

import { GenericBlock } from "./blocks/GenericBlock";
import { InterruptEventBlock } from "./blocks/InterruptEventBlock";
import { ReasoningBlock } from "./blocks/ReasoningBlock";
import { TextBlock } from "./blocks/TextBlock";
import { ToolCallBlock } from "./blocks/ToolCallBlock";

import {
  type ChatMessage,
  type MessageBlock as MessageBlockType,
} from "@/lib/api/chat-utils";

export interface MessageBlockProps {
  block: MessageBlockType;
  messageId: string;
  blockIndex: number;
  role: ChatMessage["role"];
  messageStatus?: ChatMessage["status"];
  onLayoutChangeStart?: () => void;
  onLoadBlockContent?: (messageId: string, blockId: string) => Promise<boolean>;
}

export function MessageBlock({
  block,
  messageId,
  blockIndex,
  role,
  messageStatus,
  onLayoutChangeStart,
  onLoadBlockContent,
}: MessageBlockProps) {
  const blockId = block.id || `${messageId}:${blockIndex}`;
  const isFirst = blockIndex === 0;

  switch (block.type) {
    case "reasoning":
      return (
        <ReasoningBlock
          block={block}
          fallbackBlockId={blockId}
          messageId={messageId}
          onLayoutChangeStart={onLayoutChangeStart}
          onLoadBlockContent={onLoadBlockContent}
          isFirst={isFirst}
        />
      );
    case "tool_call":
      return (
        <ToolCallBlock
          block={block}
          fallbackBlockId={blockId}
          messageId={messageId}
          messageStatus={messageStatus}
          onLayoutChangeStart={onLayoutChangeStart}
          onLoadBlockContent={onLoadBlockContent}
          isFirst={isFirst}
        />
      );
    case "interrupt_event":
      return (
        <InterruptEventBlock
          block={block}
          fallbackBlockId={blockId}
          isFirst={isFirst}
        />
      );
    case "text":
      return (
        <TextBlock
          block={block}
          fallbackBlockId={blockId}
          isAgent={role === "agent"}
          isFirst={isFirst}
        />
      );
    default:
      return (
        <GenericBlock
          block={block}
          fallbackBlockId={blockId}
          isFirst={isFirst}
        />
      );
  }
}

export function MessageContentFallback({
  hasPlainContent,
  content,
  messageId,
  role,
}: {
  hasPlainContent: boolean;
  content: string;
  messageId: string;
  role: ChatMessage["role"];
}) {
  if (hasPlainContent) {
    return (
      <TextBlock
        content={content}
        fallbackBlockId={messageId}
        isAgent={role === "agent"}
        isFirst
      />
    );
  }

  return (
    <View className="rounded-lg bg-black/20 px-3 py-2">
      <Text className="text-[11px] font-medium text-slate-400">
        Content unavailable.
      </Text>
    </View>
  );
}
