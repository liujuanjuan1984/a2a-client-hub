import { useLocalSearchParams } from "expo-router";
import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAgentFormScreen = lazy(async () => {
  const module = await import("@/screens/AgentFormScreen");
  return { default: module.AgentFormScreen };
});

export default function EditAgent() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return (
    <>
      <PageTitle title="Edit Agent" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAgentFormScreen agentId={id} />
      </Suspense>
    </>
  );
}
