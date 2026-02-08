export const queryKeys = {
  me: (token?: string | null) => ["auth", "me", token ?? "anonymous"] as const,
};
