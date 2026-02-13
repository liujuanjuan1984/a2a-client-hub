import { useLocalSearchParams } from "expo-router";

import { ChatScreen } from "@/screens/ChatScreen";

export default function ChatSession() {
  const { agentId, sessionId, source } = useLocalSearchParams<{
    agentId: string;
    sessionId: string;
    source?: "manual" | "scheduled";
  }>();

  return <ChatScreen agentId={agentId} sessionId={sessionId} source={source} />;
}
