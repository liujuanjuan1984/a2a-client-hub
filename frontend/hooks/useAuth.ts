import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { apiRequest, ApiRequestError } from "@/lib/api/client";
import {
  type AuthResponse,
  type LoginRequest,
  type RegisterRequest,
  type UserProfile,
} from "@/lib/api/types";
import { queryKeys } from "@/lib/queryKeys";
import { useSessionStore } from "@/store/session";

export const useMe = () => {
  const token = useSessionStore((state) => state.token);
  const setUserProfile = useSessionStore((state) => state.setUserProfile);
  const clearSession = useSessionStore((state) => state.clearSession);
  const previousTokenRef = useRef<string | null>(null);
  const query = useQuery({
    queryKey: queryKeys.me(),
    queryFn: () => apiRequest<UserProfile>("/auth/me"),
    enabled: Boolean(token),
    retry: 0,
  });
  const { refetch } = query;

  useEffect(() => {
    const previousToken = previousTokenRef.current;
    previousTokenRef.current = token ?? null;

    if (!token) {
      return;
    }
    if (!previousToken || previousToken === token) {
      return;
    }
    refetch().catch(() => {
      // Errors are handled by query state and downstream effects.
    });
  }, [token, refetch]);

  useEffect(() => {
    if (query.data) {
      setUserProfile(query.data);
    }
  }, [query.data, setUserProfile]);

  useEffect(() => {
    if (!query.isError || !token) {
      return;
    }
    const error = query.error;
    if (error instanceof ApiRequestError && error.status === 401) {
      clearSession();
    }
  }, [query.error, query.isError, clearSession, token]);

  return query;
};

export const useLogin = () => {
  const setSession = useSessionStore((state) => state.setSession);
  return useMutation({
    mutationFn: (payload: LoginRequest) =>
      apiRequest<AuthResponse>("/auth/login", {
        method: "POST",
        body: payload,
      }),
    onSuccess: (data) => {
      setSession({ token: data.access_token, user: data.user });
    },
  });
};

export const useRegister = () => {
  const setSession = useSessionStore((state) => state.setSession);
  return useMutation({
    mutationFn: async (payload: RegisterRequest) => {
      await apiRequest("/auth/register", {
        method: "POST",
        body: payload,
      });
      return apiRequest<AuthResponse>("/auth/login", {
        method: "POST",
        body: { email: payload.email, password: payload.password },
      });
    },
    onSuccess: (data) => {
      setSession({ token: data.access_token, user: data.user });
    },
  });
};

export const useLogout = () => {
  const clearSession = useSessionStore((state) => state.clearSession);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      try {
        await apiRequest("/auth/logout", { method: "POST" });
      } catch {
        // Best-effort: always clear local state even if the network fails.
      }
    },
    onSettled: () => {
      clearSession();
      queryClient.clear();
    },
  });
};
