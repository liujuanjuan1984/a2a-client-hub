import { useLocalSearchParams } from "expo-router";

import { OpencodeSessionMessagesScreen } from "@/screens/OpencodeSessionMessagesScreen";

export default function OpencodeSessionMessagesRoute() {
  const { agentId, sessionId } = useLocalSearchParams<{
    agentId: string;
    sessionId: string;
  }>();
  return (
    <OpencodeSessionMessagesScreen agentId={agentId} sessionId={sessionId} />
  );
}
