import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAdminHubAgentNewScreen = lazy(async () => {
  const module = await import("@/screens/admin/AdminHubAgentNewScreen");
  return { default: module.AdminHubAgentNewScreen };
});

export default function AdminHubAgentNewRoute() {
  return (
    <>
      <PageTitle title="New Shared Agent" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAdminHubAgentNewScreen />
      </Suspense>
    </>
  );
}
