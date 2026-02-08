import { useLocalSearchParams } from "expo-router";

import { AgentFormScreen } from "@/screens/AgentFormScreen";

export default function EditAgent() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <AgentFormScreen agentId={id} />;
}
