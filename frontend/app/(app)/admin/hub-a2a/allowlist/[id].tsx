import { useLocalSearchParams } from "expo-router";
import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAdminHubAgentAllowlistScreen = lazy(async () => {
  const module = await import("@/screens/admin/AdminHubAgentAllowlistScreen");
  return { default: module.AdminHubAgentAllowlistScreen };
});

export default function AdminHubAgentAllowlistRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const agentId = typeof id === "string" ? id : "";
  return (
    <>
      <PageTitle title="Agent Allowlist" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAdminHubAgentAllowlistScreen agentId={agentId} />
      </Suspense>
    </>
  );
}
