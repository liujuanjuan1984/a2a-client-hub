import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAgentListScreen = lazy(async () => {
  const module = await import("@/screens/AgentListScreen");
  return { default: module.AgentListScreen };
});

export default function Home() {
  return (
    <>
      <PageTitle title="Agents" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAgentListScreen />
      </Suspense>
    </>
  );
}
