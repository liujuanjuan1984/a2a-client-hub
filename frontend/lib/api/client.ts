import { Platform } from "react-native";

import { ENV } from "../config";
import { type ApiErrorResponse } from "./types";

import { resetAuthBoundState } from "@/lib/resetClientState";
import { useSessionStore } from "@/store/session";

export class ApiConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiConfigError";
    Object.setPrototypeOf(this, ApiConfigError.prototype);
  }
}

export class ApiRequestError extends Error {
  status: number;
  errorCode: string | null;
  upstreamError: Record<string, unknown> | null;

  constructor(
    message: string,
    status: number,
    options?: {
      errorCode?: string | null;
      upstreamError?: Record<string, unknown> | null;
    },
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.errorCode = options?.errorCode ?? null;
    this.upstreamError = options?.upstreamError ?? null;
    Object.setPrototypeOf(this, ApiRequestError.prototype);
  }
}

export class AuthExpiredError extends ApiRequestError {
  constructor(message = "Authentication expired. Please sign in again.") {
    super(message, 401, { errorCode: "auth_expired" });
    this.name = "AuthExpiredError";
    Object.setPrototypeOf(this, AuthExpiredError.prototype);
  }
}

export const isAuthFailureError = (error: unknown): boolean => {
  if (error instanceof AuthExpiredError) {
    return true;
  }
  return error instanceof ApiRequestError && error.status === 401;
};

export const isAuthorizationFailureError = (error: unknown): boolean =>
  error instanceof ApiRequestError && error.status === 403;

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

type ApiRequestOptions<Body> = {
  method?: HttpMethod;
  body?: Body;
  tokenOverride?: string;
  headers?: Record<string, string>;
  query?: Record<string, string | number | undefined | null>;
};

const buildUrl = (
  path: string,
  query?: ApiRequestOptions<unknown>["query"],
) => {
  if (
    Platform.OS !== "web" &&
    !/^https?:\/\//.test(ENV.apiBaseUrl) &&
    !path.startsWith("http")
  ) {
    throw new ApiConfigError(
      `Invalid EXPO_PUBLIC_API_BASE_URL for ${Platform.OS}: "${ENV.apiBaseUrl}". Please set an absolute URL (e.g. https://your-api-host/api/v1).`,
    );
  }

  const normalized = path.startsWith("http")
    ? path
    : `${ENV.apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
  if (!query) return normalized;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null) return;
    params.append(key, String(value));
  });
  const qs = params.toString();
  return qs ? `${normalized}?${qs}` : normalized;
};

const AUTH_LOGIN_PATH = "/auth/login";
const AUTH_REGISTER_PATH = "/auth/register";
const AUTH_REFRESH_PATH = "/auth/refresh";
const AUTH_LOGOUT_PATH = "/auth/logout";
const REFRESH_REQUEST_TIMEOUT_MS = 2_000;
const REFRESH_COOLDOWN_MS = 10_000;
const PROACTIVE_REFRESH_RATIO = 0.2;
const PROACTIVE_REFRESH_MIN_LEAD_MS = 5_000;
const PROACTIVE_REFRESH_MAX_LEAD_MS = 90_000;

type RefreshAccessTokenResult = {
  accessToken: string;
  expiresInSeconds: number | null;
};

type RefreshAccessTokenOptions = {
  force?: boolean;
  expectedAuthVersion?: number;
};

let refreshPromise: Promise<RefreshAccessTokenResult | null> | null = null;
let refreshPromiseForAuthVersion: number | null = null;
let refreshCooldownUntilMs = 0;
let authResetting = false;

const isAuthPath = (path: string) => {
  const authPaths = [
    AUTH_LOGIN_PATH,
    AUTH_REGISTER_PATH,
    AUTH_REFRESH_PATH,
    AUTH_LOGOUT_PATH,
  ];
  return authPaths.some(
    (authPath) => path === authPath || path.endsWith(authPath),
  );
};

const isUnauthorizedStatusCode = (status: number): boolean => status === 401;

const hasExpectedAuthVersion = (expectedAuthVersion?: number): boolean => {
  if (expectedAuthVersion === undefined) {
    return true;
  }
  return useSessionStore.getState().authVersion === expectedAuthVersion;
};

const parseExpiresInSeconds = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value.trim(), 10);
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return null;
};

const parseRefreshPayloadFromResponse = async (
  response: Response,
): Promise<RefreshAccessTokenResult | null> => {
  if (!response.ok) return null;
  if (response.status === 204) return null;
  try {
    const json = (await response.json()) as unknown;
    if (!json || typeof json !== "object") return null;
    const payload = json as Record<string, unknown>;
    const nestedPayload =
      payload.data && typeof payload.data === "object"
        ? (payload.data as Record<string, unknown>)
        : null;
    const tokenRaw = payload.access_token ?? nestedPayload?.access_token;
    if (typeof tokenRaw !== "string" || !tokenRaw.trim()) {
      return null;
    }
    const expiresInSeconds = parseExpiresInSeconds(
      payload.expires_in ?? nestedPayload?.expires_in,
    );
    return {
      accessToken: tokenRaw,
      expiresInSeconds,
    };
  } catch {
    // Ignore invalid JSON
  }
  return null;
};

const computeProactiveRefreshLeadMs = (ttlSeconds: number | null): number => {
  if (
    typeof ttlSeconds !== "number" ||
    !Number.isFinite(ttlSeconds) ||
    ttlSeconds <= 0
  ) {
    return 30_000;
  }
  const ttlMs = ttlSeconds * 1000;
  const calculated = Math.round(ttlMs * PROACTIVE_REFRESH_RATIO);
  const cappedUpperBound = Math.max(
    PROACTIVE_REFRESH_MIN_LEAD_MS,
    Math.min(PROACTIVE_REFRESH_MAX_LEAD_MS, Math.floor(ttlMs * 0.5)),
  );
  return Math.min(
    Math.max(calculated, PROACTIVE_REFRESH_MIN_LEAD_MS),
    cappedUpperBound,
  );
};

const applyRefreshedToken = (
  result: RefreshAccessTokenResult,
  options?: {
    expectedAuthVersion?: number;
  },
): boolean => {
  if (!hasExpectedAuthVersion(options?.expectedAuthVersion)) {
    return false;
  }
  useSessionStore
    .getState()
    .setAccessToken(result.accessToken, result.expiresInSeconds);
  return true;
};

export async function refreshAccessToken(
  options: RefreshAccessTokenOptions = {},
): Promise<RefreshAccessTokenResult | null> {
  const force = Boolean(options.force);
  const expectedAuthVersion = options.expectedAuthVersion;

  if (!hasExpectedAuthVersion(expectedAuthVersion)) {
    return null;
  }

  if (
    refreshPromise &&
    expectedAuthVersion !== undefined &&
    refreshPromiseForAuthVersion !== null &&
    refreshPromiseForAuthVersion !== expectedAuthVersion
  ) {
    return null;
  }

  if (!force && Date.now() < refreshCooldownUntilMs) {
    return null;
  }

  if (!refreshPromise) {
    const session = useSessionStore.getState();
    if (
      expectedAuthVersion !== undefined &&
      session.authVersion !== expectedAuthVersion
    ) {
      return null;
    }
    refreshPromiseForAuthVersion = session.authVersion;
    if (session.token) {
      session.setAuthStatus("refreshing");
    }
    refreshPromise = (async () => {
      const url = buildUrl(AUTH_REFRESH_PATH);
      const controller = new AbortController();
      const timer = setTimeout(() => {
        controller.abort();
      }, REFRESH_REQUEST_TIMEOUT_MS);
      try {
        const response = await fetch(url, {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
          signal: controller.signal,
        });
        return await parseRefreshPayloadFromResponse(response);
      } finally {
        clearTimeout(timer);
      }
    })()
      .catch((error) => {
        if (error instanceof ApiConfigError) {
          throw error;
        }
        if (error instanceof Error && error.name === "AbortError") {
          return null;
        }
        return null;
      })
      .finally(() => {
        refreshPromise = null;
        refreshPromiseForAuthVersion = null;
      });
  }
  let result: RefreshAccessTokenResult | null;
  try {
    result = await refreshPromise;
  } catch (error) {
    if (error instanceof ApiConfigError) {
      // A misconfigured API base URL is a hard failure; do not hide it.
      throw error;
    }
    result = null;
  }
  if (!result) {
    // Avoid repeated refresh storms when the cookie is missing/expired.
    refreshCooldownUntilMs = Date.now() + REFRESH_COOLDOWN_MS;
    if (hasExpectedAuthVersion(expectedAuthVersion)) {
      const { token, setAuthStatus } = useSessionStore.getState();
      setAuthStatus(token ? "authenticated" : "expired");
    }
    return null;
  }
  if (hasExpectedAuthVersion(expectedAuthVersion)) {
    useSessionStore.getState().setAuthStatus("authenticated");
  }
  return result;
}

export async function ensureFreshAccessToken(options?: {
  expectedAuthVersion?: number;
}): Promise<string | null> {
  const session = useSessionStore.getState();
  const token = session.token;
  if (!token) {
    return null;
  }
  if (!hasExpectedAuthVersion(options?.expectedAuthVersion)) {
    return token;
  }
  const expiresAt = session.accessTokenExpiresAtMs;
  if (!expiresAt) {
    return token;
  }

  const leadMs = computeProactiveRefreshLeadMs(session.accessTokenTtlSeconds);
  const jitterMaxMs = Math.min(10_000, Math.floor(leadMs * 0.2));
  const jitterMs =
    jitterMaxMs > 0 ? Math.floor(Math.random() * jitterMaxMs) : 0;
  const shouldRefresh = Date.now() >= expiresAt - leadMs + jitterMs;
  if (!shouldRefresh) {
    return token;
  }

  const refreshed = await refreshAccessToken({
    expectedAuthVersion: options?.expectedAuthVersion,
  });
  if (refreshed) {
    applyRefreshedToken(refreshed, {
      expectedAuthVersion: options?.expectedAuthVersion,
    });
    return refreshed.accessToken;
  }
  if (Date.now() < expiresAt) {
    return token;
  }
  handleAuthExpiredOnce({
    expectedAuthVersion: options?.expectedAuthVersion,
  });
  throw new AuthExpiredError();
}

export const handleAuthExpiredOnce = (options?: {
  expectedAuthVersion?: number;
}) => {
  if (!hasExpectedAuthVersion(options?.expectedAuthVersion)) {
    return;
  }
  if (authResetting) {
    return;
  }
  authResetting = true;
  try {
    resetAuthBoundState();
  } finally {
    authResetting = false;
  }
};

export async function apiRequest<Response, Body = unknown>(
  path: string,
  options: ApiRequestOptions<Body> = {},
): Promise<Response> {
  const { method = "GET", body, headers = {}, tokenOverride, query } = options;
  const sessionSnapshot = useSessionStore.getState();
  let token = tokenOverride ?? sessionSnapshot.token;
  const requestAuthVersion = sessionSnapshot.authVersion;
  const url = buildUrl(path, query);
  const shouldAttemptRefresh =
    !tokenOverride && !("Authorization" in headers) && !isAuthPath(path);

  const execute = async (accessToken: string | null) => {
    return await fetch(url, {
      method,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  };

  if (shouldAttemptRefresh) {
    token = await ensureFreshAccessToken({
      expectedAuthVersion: requestAuthVersion,
    });
  }

  let response = await execute(token);

  if (isUnauthorizedStatusCode(response.status) && shouldAttemptRefresh) {
    const refreshed = await refreshAccessToken({
      force: true,
      expectedAuthVersion: requestAuthVersion,
    });
    if (refreshed) {
      applyRefreshedToken(refreshed, {
        expectedAuthVersion: requestAuthVersion,
      });
      response = await execute(refreshed.accessToken);

      if (isUnauthorizedStatusCode(response.status)) {
        handleAuthExpiredOnce({
          expectedAuthVersion: requestAuthVersion,
        });
        throw new AuthExpiredError();
      }
    } else {
      handleAuthExpiredOnce({
        expectedAuthVersion: requestAuthVersion,
      });
      throw new AuthExpiredError();
    }
  }

  if (!response.ok) {
    let details: ApiErrorResponse | undefined;
    try {
      details = await response.json();
    } catch {
      // Ignore invalid JSON
    }

    const errorBody = details?.detail || details?.message || details?.error;
    const detailsRecord =
      details && typeof details === "object" && !Array.isArray(details)
        ? (details as Record<string, unknown>)
        : undefined;
    const detailRecord =
      details?.detail &&
      typeof details.detail === "object" &&
      !Array.isArray(details.detail)
        ? (details.detail as Record<string, unknown>)
        : undefined;
    const errorCode =
      typeof detailsRecord?.error_code === "string"
        ? detailsRecord.error_code
        : typeof detailRecord?.error_code === "string"
          ? detailRecord.error_code
          : null;
    const upstreamError =
      detailRecord?.upstream_error &&
      typeof detailRecord.upstream_error === "object" &&
      !Array.isArray(detailRecord.upstream_error)
        ? (detailRecord.upstream_error as Record<string, unknown>)
        : detailsRecord?.upstream_error &&
            typeof detailsRecord.upstream_error === "object" &&
            !Array.isArray(detailsRecord.upstream_error)
          ? (detailsRecord.upstream_error as Record<string, unknown>)
          : null;
    let errorMessage: string;

    if (typeof errorBody === "string") {
      errorMessage = errorBody;
    } else if (Array.isArray(errorBody)) {
      errorMessage = errorBody
        .map((err) => {
          const msg = err.msg || err.message || "Unknown error";
          const loc = err.loc?.join(".") ?? "";
          return loc ? `${loc}: ${msg}` : msg;
        })
        .join("; ");
    } else if (errorBody && typeof errorBody === "object") {
      const messageField =
        "message" in errorBody &&
        typeof (errorBody as { message?: unknown }).message === "string"
          ? (errorBody as { message: string }).message.trim()
          : "";
      errorMessage = messageField || JSON.stringify(errorBody);
    } else {
      errorMessage = `Request failed (${response.status})`;
    }

    if (errorCode) {
      errorMessage = `${errorMessage} [${errorCode}]`;
    }

    throw new ApiRequestError(errorMessage, response.status, {
      errorCode,
      upstreamError,
    });
  }

  if (response.status === 204) {
    return {} as Response;
  }

  return response.json() as Promise<Response>;
}
