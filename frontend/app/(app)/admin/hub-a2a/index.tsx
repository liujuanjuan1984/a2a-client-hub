import { PageTitle } from "@/components/layout/PageTitle";
import { AdminHubAgentsScreen } from "@/screens/admin/AdminHubAgentsScreen";

export default function AdminHubAgentsRoute() {
  return (
    <>
      <PageTitle title="Shared Agents" />
      <AdminHubAgentsScreen />
    </>
  );
}
