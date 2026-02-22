import { PageTitle } from "@/components/layout/PageTitle";
import { AdminHomeScreen } from "@/screens/admin/AdminHomeScreen";

export default function AdminHomeRoute() {
  return (
    <>
      <PageTitle title="Admin" />
      <AdminHomeScreen />
    </>
  );
}
