import { AdminHubAgentsScreen } from "@/screens/admin/AdminHubAgentsScreen";
import { PageTitle } from "@/components/layout/PageTitle";

export default function AdminHubAgentsRoute() {
  return (
    <>
      <PageTitle title="Shared Agents" />
      <AdminHubAgentsScreen />
    </>
  );
}
