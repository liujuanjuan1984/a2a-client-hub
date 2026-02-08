import { Platform } from "react-native";

import { ENV } from "../config";
import { type ApiErrorResponse } from "./types";

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

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    Object.setPrototypeOf(this, ApiRequestError.prototype);
  }
}

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
const AUTH_REFRESH_PATH = "/auth/refresh";
const AUTH_LOGOUT_PATH = "/auth/logout";

let refreshPromise: Promise<string | null> | null = null;
let refreshCooldownUntilMs = 0;

const isAuthPath = (path: string) => {
  const authPaths = [AUTH_LOGIN_PATH, AUTH_REFRESH_PATH, AUTH_LOGOUT_PATH];
  return authPaths.some(
    (authPath) => path === authPath || path.endsWith(authPath),
  );
};

const parseAccessTokenFromResponse = async (
  response: Response,
): Promise<string | null> => {
  if (!response.ok) return null;
  if (response.status === 204) return null;
  try {
    const json = (await response.json()) as unknown;
    if (json && typeof json === "object" && "access_token" in json) {
      const token = (json as { access_token?: unknown }).access_token;
      return typeof token === "string" ? token : null;
    }
  } catch {
    // Ignore invalid JSON
  }
  return null;
};

export async function refreshAccessToken(): Promise<string | null> {
  if (Date.now() < refreshCooldownUntilMs) {
    return null;
  }

  if (!refreshPromise) {
    refreshPromise = (async () => {
      const url = buildUrl(AUTH_REFRESH_PATH);
      const response = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      });
      return await parseAccessTokenFromResponse(response);
    })()
      .catch((error) => {
        if (error instanceof ApiConfigError) {
          throw error;
        }
        return null;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  let result: string | null;
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
    refreshCooldownUntilMs = Date.now() + 10_000;
  }
  return result;
}

export async function apiRequest<Response, Body = unknown>(
  path: string,
  options: ApiRequestOptions<Body> = {},
): Promise<Response> {
  const { method = "GET", body, headers = {}, tokenOverride, query } = options;
  const token = tokenOverride ?? useSessionStore.getState().token;
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

  let response = await execute(token);

  if (response.status === 401 && shouldAttemptRefresh) {
    const refreshedToken = await refreshAccessToken();
    if (refreshedToken) {
      useSessionStore.getState().setAccessToken(refreshedToken);
      response = await execute(refreshedToken);

      // If we still can't authenticate after a refresh, stop retrying and clear
      // local state to avoid request->refresh storms.
      if (response.status === 401) {
        useSessionStore.getState().clearSession();
      }
    } else {
      useSessionStore.getState().clearSession();
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
      errorMessage = JSON.stringify(errorBody);
    } else {
      errorMessage = `Request failed (${response.status})`;
    }

    throw new ApiRequestError(errorMessage, response.status);
  }

  if (response.status === 204) {
    return {} as Response;
  }

  return response.json() as Promise<Response>;
}
