import { type Href, Redirect, useLocalSearchParams } from "expo-router";

import { useChatStore } from "@/store/chat";

export default function ChatAgentRedirect() {
  const { agentId } = useLocalSearchParams<{ agentId: string }>();
  const sessionId = useChatStore.getState().generateSessionId();

  const href = {
    pathname: "/(app)/chat/[agentId]/[sessionId]",
    params: { agentId, sessionId },
  } as unknown as Href;

  return <Redirect href={href} />;
}
