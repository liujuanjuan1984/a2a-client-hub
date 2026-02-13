import { useLocalSearchParams } from "expo-router";

import { ChatScreen } from "@/screens/ChatScreen";

export default function ChatSession() {
  const { agentId, sessionId } = useLocalSearchParams<{
    agentId: string;
    sessionId: string;
  }>();

  return <ChatScreen agentId={agentId} sessionId={sessionId} />;
}
