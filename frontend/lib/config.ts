const apiBaseUrl = process.env.EXPO_PUBLIC_API_BASE_URL ?? "/api/v1";

const normalizeBase = (value: string) => value.replace(/\/$/, "");

export const ENV = {
  // Do not hardcode environment-specific domains in the repo.
  // On web deployments that reverse-proxy `/api/v1` on the same origin, the
  // default `/api/v1` works without any env var.
  apiBaseUrl: normalizeBase(apiBaseUrl),
};
