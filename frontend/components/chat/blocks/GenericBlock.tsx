import React from "react";
import { Text, View } from "react-native";

import { type MessageBlock } from "@/lib/api/chat-utils";

interface GenericBlockProps {
  block: MessageBlock;
  fallbackBlockId: string;
  isFirst?: boolean;
}

export function GenericBlock({
  block,
  fallbackBlockId,
  isFirst,
}: GenericBlockProps) {
  const blockText = block.content;
  const blockId = block.id || fallbackBlockId;

  return (
    <View
      key={blockId}
      className={`${!isFirst ? "mt-3" : ""} rounded-xl bg-black/40 p-3`}
    >
      <Text className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
        {block.type}
      </Text>
      <Text
        selectable
        className="mt-2 break-all text-[11px] leading-5 text-slate-400 font-normal"
      >
        {blockText}
      </Text>
    </View>
  );
}
