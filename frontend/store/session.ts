import { create } from "zustand";

import { type UserProfile } from "@/lib/api/types";

export type SessionState = {
  token: string | null;
  user: UserProfile | null;
  hydrated: boolean;
  setAccessToken: (token: string | null) => void;
  setSession: (payload: { token: string; user: UserProfile }) => void;
  clearSession: () => void;
  setUserProfile: (user: UserProfile | null) => void;
  setHydrated: (value: boolean) => void;
};

export const useSessionStore = create<SessionState>()((set) => ({
  token: null,
  user: null,
  hydrated: false,
  setAccessToken: (token) => set({ token }),
  setSession: ({ token, user }) => set({ token, user }),
  clearSession: () => set({ token: null, user: null }),
  setUserProfile: (user) => set({ user }),
  setHydrated: (value) => set({ hydrated: value }),
}));
