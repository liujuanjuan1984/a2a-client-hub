import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazySessionsScreen = lazy(async () => {
  const module = await import("@/screens/SessionsScreen");
  return { default: module.SessionsScreen };
});

export default function SessionsPage() {
  return (
    <>
      <PageTitle title="Sessions" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazySessionsScreen />
      </Suspense>
    </>
  );
}
