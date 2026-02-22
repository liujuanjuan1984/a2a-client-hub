import { AdminHubAgentNewScreen } from "@/screens/admin/AdminHubAgentNewScreen";
import { PageTitle } from "@/components/layout/PageTitle";

export default function AdminHubAgentNewRoute() {
  return (
    <>
      <PageTitle title="New Shared Agent" />
      <AdminHubAgentNewScreen />
    </>
  );
}
