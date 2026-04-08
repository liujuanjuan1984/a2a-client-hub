import { useLocalSearchParams } from "expo-router";
import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAdminHubAgentDetailScreen = lazy(async () => {
  const module = await import("@/screens/admin/AdminHubAgentDetailScreen");
  return { default: module.AdminHubAgentDetailScreen };
});

export default function AdminHubAgentDetailRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const agentId = typeof id === "string" ? id : "";
  return (
    <>
      <PageTitle title="Shared Agent" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAdminHubAgentDetailScreen agentId={agentId} />
      </Suspense>
    </>
  );
}
