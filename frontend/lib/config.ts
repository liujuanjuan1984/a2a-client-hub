import { AllowlistError } from "./api/client";

const apiBaseUrl = process.env.EXPO_PUBLIC_API_BASE_URL ?? "/api/v1";
const apiAllowlistRaw = process.env.EXPO_PUBLIC_API_ALLOWLIST ?? "";

const normalizeBase = (value: string) => value.replace(/\/$/, "");

const isHostAllowed = (url: string, allowlist: string[]): boolean => {
  try {
    const hostname = new URL(url).hostname;
    return allowlist.some((allowedHost) => allowedHost === hostname);
  } catch (error) {
    console.warn("Invalid URL in allowlist check:", url, error);
    return false;
  }
};

const ALLOWED_HOSTS = apiAllowlistRaw
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

if (!isHostAllowed(apiBaseUrl, ALLOWED_HOSTS)) {
  throw new AllowlistError(
    `API base URL host \"${new URL(apiBaseUrl).hostname}\" is not in the allowlist. Please update EXPO_PUBLIC_API_ALLOWLIST.`,
    new URL(apiBaseUrl).hostname,
  );
}

export const ENV = {
  // Do not hardcode environment-specific domains in the repo.
  // On web deployments that reverse-proxy `/api/v1` on the same origin, the
  // default `/api/v1` works without any env var.
  apiBaseUrl: normalizeBase(apiBaseUrl),
  apiAllowlist: apiAllowlistRaw,
};
