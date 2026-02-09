import { useRouter } from "expo-router";
import { useEffect, useMemo } from "react";

import { useSessionStore } from "@/store/session";

export const useRequireAdmin = () => {
  const router = useRouter();
  const hydrated = useSessionStore((state) => state.hydrated);
  const user = useSessionStore((state) => state.user);

  const isAdmin = Boolean(user?.is_superuser);
  const isReady = hydrated && user !== null;

  useEffect(() => {
    if (!isReady) return;
    if (isAdmin) return;
    router.replace("/");
  }, [isAdmin, isReady, router]);

  return useMemo(
    () => ({
      isReady,
      isAdmin,
    }),
    [isAdmin, isReady],
  );
};
