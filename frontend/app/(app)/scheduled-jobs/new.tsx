import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyScheduledJobFormScreen = lazy(async () => {
  const module = await import("@/screens/ScheduledJobFormScreen");
  return { default: module.ScheduledJobFormScreen };
});

export default function NewScheduledJobPage() {
  return (
    <>
      <PageTitle title="New Job" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyScheduledJobFormScreen />
      </Suspense>
    </>
  );
}
