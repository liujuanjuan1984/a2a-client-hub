import { create } from "zustand";

import { type UserProfile } from "@/lib/api/types";

export type AuthStatus = "authenticated" | "refreshing" | "expired";

const normalizeExpiresInSeconds = (
  value: number | null | undefined,
): number | null => {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return value > 0 ? value : null;
};

const toExpiresAtMs = (expiresInSeconds: number | null): number | null => {
  if (expiresInSeconds === null) {
    return null;
  }
  return Date.now() + expiresInSeconds * 1000;
};

type SessionState = {
  token: string | null;
  user: UserProfile | null;
  accessTokenExpiresAtMs: number | null;
  accessTokenTtlSeconds: number | null;
  authStatus: AuthStatus;
  authVersion: number;
  hydrated: boolean;
  setAccessToken: (
    token: string | null,
    expiresInSeconds?: number | null,
  ) => void;
  setSession: (payload: {
    token: string;
    user: UserProfile;
    expiresInSeconds?: number | null;
  }) => void;
  clearSession: () => void;
  setUserProfile: (user: UserProfile | null) => void;
  setAuthStatus: (status: AuthStatus) => void;
  setHydrated: (value: boolean) => void;
};

export const useSessionStore = create<SessionState>()((set) => ({
  token: null,
  user: null,
  accessTokenExpiresAtMs: null,
  accessTokenTtlSeconds: null,
  authStatus: "expired",
  authVersion: 0,
  hydrated: false,
  setAccessToken: (token, expiresInSeconds) =>
    set((state) => {
      const normalizedTtl = normalizeExpiresInSeconds(expiresInSeconds);
      return {
        token,
        accessTokenTtlSeconds:
          normalizedTtl ?? (token ? state.accessTokenTtlSeconds : null),
        accessTokenExpiresAtMs:
          normalizedTtl !== null
            ? toExpiresAtMs(normalizedTtl)
            : token
              ? state.accessTokenExpiresAtMs
              : null,
        authStatus: token ? "authenticated" : "expired",
        authVersion: state.authVersion + 1,
      };
    }),
  setSession: ({ token, user, expiresInSeconds }) =>
    set((state) => {
      const normalizedTtl = normalizeExpiresInSeconds(expiresInSeconds);
      return {
        token,
        user,
        accessTokenTtlSeconds: normalizedTtl,
        accessTokenExpiresAtMs: toExpiresAtMs(normalizedTtl),
        authStatus: "authenticated",
        authVersion: state.authVersion + 1,
      };
    }),
  clearSession: () =>
    set((state) => ({
      token: null,
      user: null,
      accessTokenExpiresAtMs: null,
      accessTokenTtlSeconds: null,
      authStatus: "expired",
      authVersion: state.authVersion + 1,
    })),
  setUserProfile: (user) => set({ user }),
  setAuthStatus: (authStatus) => set({ authStatus }),
  setHydrated: (value) => set({ hydrated: value }),
}));
