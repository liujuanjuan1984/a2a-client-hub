import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAgentFormScreen = lazy(async () => {
  const module = await import("@/screens/AgentFormScreen");
  return { default: module.AgentFormScreen };
});

export default function NewAgent() {
  return (
    <>
      <PageTitle title="New Agent" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAgentFormScreen />
      </Suspense>
    </>
  );
}
