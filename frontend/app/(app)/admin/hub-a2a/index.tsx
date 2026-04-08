import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAdminHubAgentsScreen = lazy(async () => {
  const module = await import("@/screens/admin/AdminHubAgentsScreen");
  return { default: module.AdminHubAgentsScreen };
});

export default function AdminHubAgentsRoute() {
  return (
    <>
      <PageTitle title="Shared Agents" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAdminHubAgentsScreen />
      </Suspense>
    </>
  );
}
