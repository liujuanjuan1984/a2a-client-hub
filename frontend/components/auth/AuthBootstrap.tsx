import { useEffect, useRef } from "react";

import { ApiConfigError, refreshAccessToken } from "@/lib/api/client";
import { useSessionStore } from "@/store/session";

export function AuthBootstrap() {
  const hydrated = useSessionStore((state) => state.hydrated);
  const setAccessToken = useSessionStore((state) => state.setAccessToken);
  const setHydrated = useSessionStore((state) => state.setHydrated);

  const didRunRef = useRef(false);

  useEffect(() => {
    if (hydrated) return;
    if (didRunRef.current) return;
    didRunRef.current = true;

    let cancelled = false;

    (async () => {
      try {
        const token = await refreshAccessToken();
        if (cancelled) return;
        if (token) {
          setAccessToken(token);
        }
      } finally {
        if (!cancelled) {
          setHydrated(true);
        }
      }
    })().catch((error) => {
      if (error instanceof ApiConfigError) {
        console.error("[AuthBootstrap] Invalid API base URL:", error.message);
        return;
      }
      console.warn("[AuthBootstrap] Refresh failed:", {
        message: error instanceof Error ? error.message : String(error),
      });
    });

    return () => {
      cancelled = true;
    };
  }, [hydrated, setAccessToken, setHydrated]);

  return null;
}
