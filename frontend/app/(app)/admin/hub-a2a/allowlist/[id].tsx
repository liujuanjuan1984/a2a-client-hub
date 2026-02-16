import { useLocalSearchParams } from "expo-router";

import { AdminHubAgentAllowlistScreen } from "@/screens/admin/AdminHubAgentAllowlistScreen";

export default function AdminHubAgentAllowlistRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const agentId = typeof id === "string" ? id : "";
  return <AdminHubAgentAllowlistScreen agentId={agentId} />;
}
