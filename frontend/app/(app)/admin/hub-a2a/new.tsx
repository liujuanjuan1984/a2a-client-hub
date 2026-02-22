import { PageTitle } from "@/components/layout/PageTitle";
import { AdminHubAgentNewScreen } from "@/screens/admin/AdminHubAgentNewScreen";

export default function AdminHubAgentNewRoute() {
  return (
    <>
      <PageTitle title="New Shared Agent" />
      <AdminHubAgentNewScreen />
    </>
  );
}
