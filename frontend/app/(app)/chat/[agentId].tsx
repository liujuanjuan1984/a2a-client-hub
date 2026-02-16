import { type Href, Redirect, useLocalSearchParams } from "expo-router";

import { useChatStore } from "@/store/chat";

export default function ChatAgentRedirect() {
  const { agentId } = useLocalSearchParams<{ agentId: string }>();
  const conversationId = useChatStore.getState().generateConversationId();

  const href = {
    pathname: "/(app)/chat/[agentId]/[conversationId]",
    params: { agentId, conversationId },
  } as unknown as Href;

  return <Redirect href={href} />;
}
