import { lazy, Suspense } from "react";

import { PageTitle } from "@/components/layout/PageTitle";
import { RouteScreenFallback } from "@/components/layout/RouteScreenFallback";

const LazyRegisterScreen = lazy(async () => {
  const module = await import("@/screens/RegisterScreen");
  return { default: module.RegisterScreen };
});

export default function Register() {
  return (
    <>
      <PageTitle title="Register" />
      <Suspense fallback={<RouteScreenFallback />}>
        <LazyRegisterScreen />
      </Suspense>
    </>
  );
}
