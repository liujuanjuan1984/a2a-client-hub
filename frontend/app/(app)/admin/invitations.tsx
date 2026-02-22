import { PageTitle } from "@/components/layout/PageTitle";
import { AdminInvitationsScreen } from "@/screens/admin/AdminInvitationsScreen";

export default function AdminInvitationsRoute() {
  return (
    <>
      <PageTitle title="Invitations" />
      <AdminInvitationsScreen />
    </>
  );
}
