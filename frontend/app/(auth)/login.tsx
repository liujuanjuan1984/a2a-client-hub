import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyLoginScreen = lazy(async () => {
  const module = await import("@/screens/LoginScreen");
  return { default: module.LoginScreen };
});

export default function Login() {
  return (
    <>
      <PageTitle title="Login" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyLoginScreen />
      </Suspense>
    </>
  );
}
