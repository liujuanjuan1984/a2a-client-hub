import { lazy, Suspense } from "react";

import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAdminProxyAllowlistScreen = lazy(async () => {
  const module = await import("@/screens/admin/AdminProxyAllowlistScreen");
  return { default: module.AdminProxyAllowlistScreen };
});

export default function Page() {
  return (
    <Suspense fallback={<RouteScreenFallback />}>
      <LazyAdminProxyAllowlistScreen />
    </Suspense>
  );
}
