import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyAdminInvitationsScreen = lazy(async () => {
  const module = await import("@/screens/admin/AdminInvitationsScreen");
  return { default: module.AdminInvitationsScreen };
});

export default function AdminInvitationsRoute() {
  return (
    <>
      <PageTitle title="Invitations" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyAdminInvitationsScreen />
      </Suspense>
    </>
  );
}
