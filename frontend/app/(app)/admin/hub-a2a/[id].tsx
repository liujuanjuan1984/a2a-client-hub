import { useLocalSearchParams } from "expo-router";

import { PageTitle } from "@/components/layout/PageTitle";
import { AdminHubAgentDetailScreen } from "@/screens/admin/AdminHubAgentDetailScreen";

export default function AdminHubAgentDetailRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const agentId = typeof id === "string" ? id : "";
  return (
    <>
      <PageTitle title="Shared Agent" />
      <AdminHubAgentDetailScreen agentId={agentId} />
    </>
  );
}
