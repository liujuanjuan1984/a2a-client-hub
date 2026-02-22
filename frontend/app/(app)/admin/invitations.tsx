import { AdminInvitationsScreen } from "@/screens/admin/AdminInvitationsScreen";
import { PageTitle } from "@/components/layout/PageTitle";

export default function AdminInvitationsRoute() {
  return (
    <>
      <PageTitle title="Invitations" />
      <AdminInvitationsScreen />
    </>
  );
}
