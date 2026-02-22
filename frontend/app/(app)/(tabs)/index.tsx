import { AgentListScreen } from "@/screens/AgentListScreen";
import { PageTitle } from "@/components/layout/PageTitle";

export default function Home() {
  return (
    <>
      <PageTitle title="Agents" />
      <AgentListScreen />
    </>
  );
}
