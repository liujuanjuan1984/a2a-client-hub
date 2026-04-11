import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAccountSecurityScreen = lazy(async () => {
  const module = await import("@/screens/AccountSecurityScreen");
  return { default: module.AccountSecurityScreen };
});

export default function AccountRoute() {
  return (
    <>
      <PageTitle title="Account" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAccountSecurityScreen />
      </Suspense>
    </>
  );
}
