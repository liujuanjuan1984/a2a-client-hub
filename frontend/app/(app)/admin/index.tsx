import { AdminHomeScreen } from "@/screens/admin/AdminHomeScreen";
import { PageTitle } from "@/components/layout/PageTitle";

export default function AdminHomeRoute() {
  return (
    <>
      <PageTitle title="Admin" />
      <AdminHomeScreen />
    </>
  );
}
