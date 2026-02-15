import { useLocalSearchParams } from "expo-router";

import { ChatScreen } from "@/screens/ChatScreen";

export default function ChatSession() {
  const { agentId, conversationId } = useLocalSearchParams<{
    agentId: string;
    conversationId: string;
  }>();

  return <ChatScreen agentId={agentId} conversationId={conversationId} />;
}
