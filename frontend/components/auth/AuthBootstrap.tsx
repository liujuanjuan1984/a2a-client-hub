import { useEffect, useRef } from "react";
import { AppState, type AppStateStatus } from "react-native";

import {
  ApiConfigError,
  AuthRecoverableError,
  computeProactiveRefreshLeadMs,
  ensureFreshAccessToken,
  refreshAccessToken,
} from "@/lib/api/client";
import { useSessionStore } from "@/store/session";

const RECOVERY_RETRY_DELAY_MS = 5_000;

export function AuthBootstrap() {
  const hydrated = useSessionStore((state) => state.hydrated);
  const token = useSessionStore((state) => state.token);
  const accessTokenExpiresAtMs = useSessionStore(
    (state) => state.accessTokenExpiresAtMs,
  );
  const accessTokenTtlSeconds = useSessionStore(
    (state) => state.accessTokenTtlSeconds,
  );
  const authStatus = useSessionStore((state) => state.authStatus);
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
        const result = await refreshAccessToken();
        if (cancelled) return;
        if (result) {
          setAccessToken(result.accessToken, result.expiresInSeconds);
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

  useEffect(() => {
    if (!hydrated) return;

    const ensureTokenFresh = () => {
      ensureFreshAccessToken().catch((error) => {
        if (error instanceof ApiConfigError) {
          console.error("[AuthBootstrap] Invalid API base URL:", error.message);
        }
      });
    };

    const onAppStateChange = (state: AppStateStatus) => {
      if (state === "active") {
        ensureTokenFresh();
      }
    };

    const appStateSub = AppState.addEventListener("change", onAppStateChange);
    const isWeb =
      typeof document !== "undefined" && typeof window !== "undefined";

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        ensureTokenFresh();
      }
    };

    const onOnline = () => {
      ensureTokenFresh();
    };

    if (isWeb) {
      document.addEventListener("visibilitychange", onVisibilityChange);
      window.addEventListener("online", onOnline);
    }

    return () => {
      appStateSub.remove();
      if (isWeb) {
        document.removeEventListener("visibilitychange", onVisibilityChange);
        window.removeEventListener("online", onOnline);
      }
    };
  }, [hydrated]);

  useEffect(() => {
    if (!hydrated || !token || !accessTokenExpiresAtMs) {
      return;
    }

    const scheduleDelayMs =
      authStatus === "recovering"
        ? RECOVERY_RETRY_DELAY_MS
        : Math.max(
            0,
            accessTokenExpiresAtMs -
              computeProactiveRefreshLeadMs(accessTokenTtlSeconds) -
              Date.now(),
          );

    const timer = setTimeout(() => {
      ensureFreshAccessToken().catch((error) => {
        if (error instanceof ApiConfigError) {
          console.error("[AuthBootstrap] Invalid API base URL:", error.message);
          return;
        }
        if (error instanceof AuthRecoverableError) {
          return;
        }
        console.warn("[AuthBootstrap] Timed refresh failed:", {
          message: error instanceof Error ? error.message : String(error),
        });
      });
    }, scheduleDelayMs);

    return () => {
      clearTimeout(timer);
    };
  }, [
    accessTokenExpiresAtMs,
    accessTokenTtlSeconds,
    authStatus,
    hydrated,
    token,
  ]);

  return null;
}
