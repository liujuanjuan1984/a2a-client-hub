import { useLocalSearchParams } from "expo-router";
import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyScheduledJobFormScreen = lazy(async () => {
  const module = await import("@/screens/ScheduledJobFormScreen");
  return { default: module.ScheduledJobFormScreen };
});

export default function EditScheduledJobPage() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  return (
    <>
      <PageTitle title="Edit Job" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyScheduledJobFormScreen
          jobId={typeof id === "string" ? id : undefined}
        />
      </Suspense>
    </>
  );
}
