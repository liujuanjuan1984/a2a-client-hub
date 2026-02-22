import { useLocalSearchParams } from "expo-router";

import { AdminHubAgentAllowlistScreen } from "@/screens/admin/AdminHubAgentAllowlistScreen";
import { PageTitle } from "@/components/layout/PageTitle";

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
