import { useLocalSearchParams } from "expo-router";

import { PageTitle } from "@/components/layout/PageTitle";
import { AgentFormScreen } from "@/screens/AgentFormScreen";

export default function EditAgent() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return (
    <>
      <PageTitle title="Edit Agent" />
      <AgentFormScreen agentId={id} />
    </>
  );
}
