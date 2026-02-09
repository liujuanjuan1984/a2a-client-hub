import { useLocalSearchParams } from "expo-router";

import { AdminHubAgentDetailScreen } from "@/screens/admin/AdminHubAgentDetailScreen";

export default function AdminHubAgentDetailRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const agentId = typeof id === "string" ? id : "";
  return <AdminHubAgentDetailScreen agentId={agentId} />;
}
