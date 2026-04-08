import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyScheduledJobsScreen = lazy(async () => {
  const module = await import("@/screens/ScheduledJobsScreen");
  return { default: module.ScheduledJobsScreen };
});

export default function ScheduledJobsPage() {
  return (
    <>
      <PageTitle title="Scheduled Jobs" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyScheduledJobsScreen />
      </Suspense>
    </>
  );
}
