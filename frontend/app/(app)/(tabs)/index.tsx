import { PageTitle } from "@/components/layout/PageTitle";
import { AgentListScreen } from "@/screens/AgentListScreen";

export default function Home() {
  return (
    <>
      <PageTitle title="Agents" />
      <AgentListScreen />
    </>
  );
}
