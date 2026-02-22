import { useLocalSearchParams } from "expo-router";

import { AdminHubAgentDetailScreen } from "@/screens/admin/AdminHubAgentDetailScreen";
import { PageTitle } from "@/components/layout/PageTitle";

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
