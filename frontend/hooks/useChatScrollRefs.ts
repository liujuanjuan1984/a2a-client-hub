import { useRef } from "react";
import { FlatList } from "react-native";

import { type ChatMessage } from "@/lib/api/chat-utils";

export function useChatScrollRefs() {
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const scrollOffsetRef = useRef(0);
  const contentHeightRef = useRef(0);

  return {
    listRef,
    scrollOffsetRef,
    contentHeightRef,
  };
}
