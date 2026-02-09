import { useLocalSearchParams } from "expo-router";

import { OpencodeSessionsScreen } from "@/screens/OpencodeSessionsScreen";

export default function OpencodeSessionsRoute() {
  const { agentId } = useLocalSearchParams<{ agentId: string }>();
  return <OpencodeSessionsScreen agentId={agentId} />;
}
