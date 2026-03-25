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
  source: string | null;
  jsonrpcCode: number | null;
  missingParams: { name: string; required: boolean }[] | null;
  upstreamError: Record<string, unknown> | null;

  constructor(
    message: string,
    status: number,
    options?: {
      errorCode?: string | null;
      source?: string | null;
      jsonrpcCode?: number | null;
      missingParams?: { name: string; required: boolean }[] | null;
      upstreamError?: Record<string, unknown> | null;
    },
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.errorCode = options?.errorCode ?? null;
    this.source = options?.source ?? null;
    this.jsonrpcCode = options?.jsonrpcCode ?? null;
    this.missingParams = options?.missingParams ?? null;
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

export class AuthRecoverableError extends ApiRequestError {
  constructor(message = "Authentication recovery in progress. Please retry.") {
    super(message, 503, { errorCode: "auth_recovering" });
    this.name = "AuthRecoverableError";
    Object.setPrototypeOf(this, AuthRecoverableError.prototype);
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

type JsonRecord = Record<string, unknown>;

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
export const AUTH_RECOVERY_MAX_DURATION_MS = 2 * 60 * 1000;
export const AUTH_RECOVERY_MAX_RETRIES = 12;

type RefreshAccessTokenResult = {
  accessToken: string;
  expiresInSeconds: number | null;
};

type RefreshFailureReason = "unauthorized" | "transient";

type RefreshAccessTokenOutcome = {
  result: RefreshAccessTokenResult | null;
  failureReason: RefreshFailureReason | null;
  didExpireSession: boolean;
};

type RefreshAccessTokenOptions = {
  force?: boolean;
  expectedAuthVersion?: number;
};

let refreshPromise: Promise<RefreshAccessTokenOutcome> | null = null;
let refreshPromiseForAuthVersion: number | null = null;
let refreshCooldownUntilMs = 0;
let authResetting = false;
let lastRefreshFailureReason: RefreshFailureReason | null = null;

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

export const computeProactiveRefreshLeadMs = (
  ttlSeconds: number | null,
): number => {
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

const buildRefreshFailureOutcome = (
  response: Response,
  result: RefreshAccessTokenResult | null,
): RefreshAccessTokenOutcome => {
  if (result) {
    return {
      result,
      failureReason: null,
      didExpireSession: false,
    };
  }

  return {
    result: null,
    failureReason:
      response.status === 401 || response.status === 403
        ? "unauthorized"
        : "transient",
    didExpireSession: false,
  };
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

const beginAuthRecovery = (options?: {
  expectedAuthVersion?: number;
}): void => {
  if (!hasExpectedAuthVersion(options?.expectedAuthVersion)) {
    return;
  }
  const session = useSessionStore.getState();
  if (!session.token) {
    return;
  }
  session.beginAuthRecovery();
};

export const hasExceededAuthRecoveryLimits = (options?: {
  expectedAuthVersion?: number;
  nowMs?: number;
}): boolean => {
  if (!hasExpectedAuthVersion(options?.expectedAuthVersion)) {
    return false;
  }
  const session = useSessionStore.getState();
  if (!session.token || session.recoveryStartedAtMs === null) {
    return false;
  }
  const nowMs = options?.nowMs ?? Date.now();
  return (
    nowMs - session.recoveryStartedAtMs >= AUTH_RECOVERY_MAX_DURATION_MS ||
    session.recoveryRetryCount >= AUTH_RECOVERY_MAX_RETRIES
  );
};

export const refreshAccessTokenWithOutcome = async (
  options: RefreshAccessTokenOptions = {},
): Promise<RefreshAccessTokenOutcome> => {
  const force = Boolean(options.force);
  const expectedAuthVersion = options.expectedAuthVersion;

  if (!hasExpectedAuthVersion(expectedAuthVersion)) {
    return { result: null, failureReason: null, didExpireSession: false };
  }

  if (
    refreshPromise &&
    expectedAuthVersion !== undefined &&
    refreshPromiseForAuthVersion !== null &&
    refreshPromiseForAuthVersion !== expectedAuthVersion
  ) {
    return { result: null, failureReason: null, didExpireSession: false };
  }

  if (!force && Date.now() < refreshCooldownUntilMs) {
    return {
      result: null,
      failureReason: lastRefreshFailureReason ?? "transient",
      didExpireSession: false,
    };
  }

  if (!refreshPromise) {
    const session = useSessionStore.getState();
    if (
      expectedAuthVersion !== undefined &&
      session.authVersion !== expectedAuthVersion
    ) {
      return { result: null, failureReason: null, didExpireSession: false };
    }
    const refreshAuthVersion = session.authVersion;
    refreshPromiseForAuthVersion = refreshAuthVersion;
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
        const parsed = await parseRefreshPayloadFromResponse(response);
        return buildRefreshFailureOutcome(response, parsed);
      } finally {
        clearTimeout(timer);
      }
    })()
      .catch((error): RefreshAccessTokenOutcome => {
        if (error instanceof ApiConfigError) {
          throw error;
        }
        return {
          result: null,
          failureReason: "transient",
          didExpireSession: false,
        };
      })
      .then((outcome) => {
        if (outcome.result) {
          lastRefreshFailureReason = null;
          if (hasExpectedAuthVersion(refreshAuthVersion)) {
            useSessionStore.getState().setAuthStatus("authenticated");
          }
          return {
            result: outcome.result,
            failureReason: null,
            didExpireSession: false,
          };
        }

        const failureReason = outcome.failureReason ?? "transient";
        lastRefreshFailureReason = failureReason;
        refreshCooldownUntilMs = Date.now() + REFRESH_COOLDOWN_MS;

        if (!hasExpectedAuthVersion(refreshAuthVersion)) {
          return {
            result: null,
            failureReason,
            didExpireSession: false,
          };
        }

        const currentSession = useSessionStore.getState();
        if (!currentSession.token) {
          currentSession.setAuthStatus("expired");
          return {
            result: null,
            failureReason,
            didExpireSession: false,
          };
        }

        if (failureReason === "transient") {
          if (
            hasExceededAuthRecoveryLimits({
              expectedAuthVersion: refreshAuthVersion,
            })
          ) {
            handleAuthExpiredOnce({
              expectedAuthVersion: refreshAuthVersion,
            });
            return {
              result: null,
              failureReason,
              didExpireSession: true,
            };
          }

          beginAuthRecovery({
            expectedAuthVersion: refreshAuthVersion,
          });
          return {
            result: null,
            failureReason,
            didExpireSession: false,
          };
        }

        currentSession.setAuthStatus("authenticated");
        return {
          result: null,
          failureReason,
          didExpireSession: false,
        };
      })
      .finally(() => {
        refreshPromise = null;
        refreshPromiseForAuthVersion = null;
      });
  }

  let outcome: RefreshAccessTokenOutcome;
  try {
    outcome = await refreshPromise;
  } catch (error) {
    if (error instanceof ApiConfigError) {
      throw error;
    }
    outcome = {
      result: null,
      failureReason: "transient",
      didExpireSession: false,
    };
  }
  return outcome;
};

export async function refreshAccessToken(
  options: RefreshAccessTokenOptions = {},
): Promise<RefreshAccessTokenResult | null> {
  const outcome = await refreshAccessTokenWithOutcome(options);
  return outcome.result;
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

  const refreshOutcome = await refreshAccessTokenWithOutcome({
    expectedAuthVersion: options?.expectedAuthVersion,
  });
  const refreshed = refreshOutcome.result;
  if (refreshOutcome.didExpireSession) {
    throw new AuthExpiredError();
  }
  if (refreshed) {
    applyRefreshedToken(refreshed, {
      expectedAuthVersion: options?.expectedAuthVersion,
    });
    return refreshed.accessToken;
  }
  if (Date.now() < expiresAt) {
    return token;
  }
  if (refreshOutcome.failureReason === "transient") {
    throw new AuthRecoverableError();
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

const shouldAttemptAuthRefresh = (
  path: string,
  tokenOverride: string | undefined,
  headers: Record<string, string>,
): boolean =>
  !tokenOverride && !("Authorization" in headers) && !isAuthPath(path);

const executeJsonRequest = async (
  url: string,
  method: HttpMethod,
  body: unknown,
  headers: Record<string, string>,
  accessToken: string | null,
): Promise<Response> => {
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

const parseApiErrorDetails = async (
  response: Response,
): Promise<{
  message: string;
  errorCode: string | null;
  source: string | null;
  jsonrpcCode: number | null;
  missingParams: { name: string; required: boolean }[] | null;
  upstreamError: JsonRecord | null;
}> => {
  let details: ApiErrorResponse | undefined;
  try {
    details = await response.json();
  } catch {
    // Ignore invalid JSON
  }

  const errorBody = details?.detail || details?.message || details?.error;
  const detailRecord =
    details?.detail &&
    typeof details.detail === "object" &&
    !Array.isArray(details.detail)
      ? (details.detail as JsonRecord)
      : undefined;
  const errorCode =
    typeof detailRecord?.error_code === "string"
      ? detailRecord.error_code
      : null;
  const source =
    typeof detailRecord?.source === "string" ? detailRecord.source : null;
  const jsonrpcCodeRaw =
    typeof detailRecord?.jsonrpc_code === "number"
      ? detailRecord.jsonrpc_code
      : null;
  const missingParamsRaw = Array.isArray(detailRecord?.missing_params)
    ? detailRecord.missing_params
    : null;
  const missingParams = missingParamsRaw
    ?.map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }
      const candidate = item as Record<string, unknown>;
      if (typeof candidate.name !== "string" || !candidate.name.trim()) {
        return null;
      }
      return {
        name: candidate.name.trim(),
        required:
          typeof candidate.required === "boolean" ? candidate.required : true,
      };
    })
    .filter(
      (item): item is { name: string; required: boolean } => item !== null,
    );
  const upstreamError =
    detailRecord?.upstream_error &&
    typeof detailRecord.upstream_error === "object" &&
    !Array.isArray(detailRecord.upstream_error)
      ? (detailRecord.upstream_error as JsonRecord)
      : null;
  let message: string;

  if (typeof errorBody === "string") {
    message = errorBody;
  } else if (Array.isArray(errorBody)) {
    message = errorBody
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
    message = messageField || JSON.stringify(errorBody);
  } else {
    message = `Request failed (${response.status})`;
  }

  if (errorCode) {
    message = `${message} [${errorCode}]`;
  }

  return {
    message,
    errorCode,
    source,
    jsonrpcCode: jsonrpcCodeRaw,
    missingParams: missingParams?.length ? missingParams : null,
    upstreamError,
  };
};

const executeRequestWithAuthRecovery = async (
  path: string,
  url: string,
  method: HttpMethod,
  body: unknown,
  headers: Record<string, string>,
  tokenOverride: string | undefined,
): Promise<Response> => {
  const sessionSnapshot = useSessionStore.getState();
  const requestAuthVersion = sessionSnapshot.authVersion;
  let token = tokenOverride ?? sessionSnapshot.token;
  const canAutoRefresh = shouldAttemptAuthRefresh(path, tokenOverride, headers);

  if (canAutoRefresh) {
    token = await ensureFreshAccessToken({
      expectedAuthVersion: requestAuthVersion,
    });
  }

  let response = await executeJsonRequest(url, method, body, headers, token);
  if (!isUnauthorizedStatusCode(response.status) || !canAutoRefresh) {
    return response;
  }

  const refreshOutcome = await refreshAccessTokenWithOutcome({
    force: true,
    expectedAuthVersion: requestAuthVersion,
  });
  const refreshed = refreshOutcome.result;
  if (refreshOutcome.didExpireSession) {
    throw new AuthExpiredError();
  }
  if (!refreshed) {
    if (refreshOutcome.failureReason === "transient") {
      throw new AuthRecoverableError();
    }
    handleAuthExpiredOnce({
      expectedAuthVersion: requestAuthVersion,
    });
    throw new AuthExpiredError();
  }

  applyRefreshedToken(refreshed, {
    expectedAuthVersion: requestAuthVersion,
  });
  response = await executeJsonRequest(
    url,
    method,
    body,
    headers,
    refreshed.accessToken,
  );
  if (isUnauthorizedStatusCode(response.status)) {
    handleAuthExpiredOnce({
      expectedAuthVersion: requestAuthVersion,
    });
    throw new AuthExpiredError();
  }
  return response;
};

export async function apiRequest<Response, Body = unknown>(
  path: string,
  options: ApiRequestOptions<Body> = {},
): Promise<Response> {
  const { method = "GET", body, headers = {}, tokenOverride, query } = options;
  const url = buildUrl(path, query);
  const response = await executeRequestWithAuthRecovery(
    path,
    url,
    method,
    body,
    headers,
    tokenOverride,
  );

  if (!response.ok) {
    const parsed = await parseApiErrorDetails(response);
    throw new ApiRequestError(parsed.message, response.status, {
      errorCode: parsed.errorCode,
      source: parsed.source,
      jsonrpcCode: parsed.jsonrpcCode,
      missingParams: parsed.missingParams,
      upstreamError: parsed.upstreamError,
    });
  }

  if (response.status === 204) {
    return {} as Response;
  }

  return response.json() as Promise<Response>;
}
