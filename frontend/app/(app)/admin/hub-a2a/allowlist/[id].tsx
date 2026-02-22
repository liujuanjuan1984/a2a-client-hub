import { useLocalSearchParams } from "expo-router";

import { PageTitle } from "@/components/layout/PageTitle";
import { AdminHubAgentAllowlistScreen } from "@/screens/admin/AdminHubAgentAllowlistScreen";

export default function AdminHubAgentAllowlistRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const agentId = typeof id === "string" ? id : "";
  return (
    <>
      <PageTitle title="Agent Allowlist" />
      <AdminHubAgentAllowlistScreen agentId={agentId} />
    </>
  );
}
