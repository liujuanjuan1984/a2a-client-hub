import { useLocalSearchParams } from "expo-router";

import { ChatScreen } from "@/screens/ChatScreen";

export default function ChatSession() {
  const { agentId, sessionId, history, source, opencodeSessionId } =
    useLocalSearchParams<{
      agentId: string;
      sessionId: string;
      history?: string;
      source?: "manual" | "scheduled";
      opencodeSessionId?: string;
    }>();

  return (
    <ChatScreen
      agentId={agentId}
      sessionId={sessionId}
      history={history === "1"}
      source={source}
      opencodeSessionId={opencodeSessionId}
    />
  );
}
