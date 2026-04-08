import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAdminHomeScreen = lazy(async () => {
  const module = await import("@/screens/admin/AdminHomeScreen");
  return { default: module.AdminHomeScreen };
});

export default function AdminHomeRoute() {
  return (
    <>
      <PageTitle title="Admin" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAdminHomeScreen />
      </Suspense>
    </>
  );
}
