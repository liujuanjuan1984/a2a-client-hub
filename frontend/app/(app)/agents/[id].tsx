import { useLocalSearchParams } from "expo-router";

import { AgentFormScreen } from "@/screens/AgentFormScreen";
import { PageTitle } from "@/components/layout/PageTitle";

export default function EditAgent() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return (
    <>
      <PageTitle title="Edit Agent" />
      <AgentFormScreen agentId={id} />
    </>
  );
}
