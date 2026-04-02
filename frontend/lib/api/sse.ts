import {
  extractStreamErrorDetails,
  type StreamErrorDetails,
  type StreamMissingParam,
} from "@/lib/api/chat-utils";
import {
  ApiRequestError,
  AuthExpiredError,
  AuthRecoverableError,
  ensureFreshAccessToken,
  handleAuthExpiredOnce,
  parseApiErrorResponse,
  refreshAccessTokenWithOutcome,
} from "@/lib/api/client";
import { useSessionStore } from "@/store/session";

type SSEEvent = {
  eventType: string;
  data: string;
};

type SSEHandlers = {
  onEvent?: (event: SSEEvent) => void;
  onData?: (data: Record<string, unknown>) => boolean | void;
  onError?: (error: Error) => void;
  onDone?: () => void;
};

type SSEReconnectOptions = {
  retries?: number;
  initialDelayMs?: number;
  maxDelayMs?: number;
  jitterMs?: number;
  onlyIfNoData?: boolean;
};

type SSEOptions = {
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;
  signal?: AbortSignal;
  idleTimeoutMs?: number;
  reconnect?: SSEReconnectOptions;
};

const DEFAULT_IDLE_TIMEOUT_MS = 45_000;
const isUnauthorizedStatusCode = (status: number) => status === 401;

export class SSEStreamError extends Error {
  errorCode: string | null;
  source: string | null;
  jsonrpcCode: number | null;
  missingParams: StreamMissingParam[] | null;
  upstreamError: Record<string, unknown> | null;

  constructor(message: string, details: Partial<StreamErrorDetails> = {}) {
    super(message);
    this.name = "SSEStreamError";
    this.errorCode = details.errorCode ?? null;
    this.source = details.source ?? null;
    this.jsonrpcCode = details.jsonrpcCode ?? null;
    this.missingParams = details.missingParams ?? null;
    this.upstreamError = details.upstreamError ?? null;
    Object.setPrototypeOf(this, SSEStreamError.prototype);
  }
}

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

const normalizeErrorCode = (value: unknown): string | null =>
  typeof value === "string" && value.trim().length > 0 ? value.trim() : null;

const parseSseError = (data: string): SSEStreamError => {
  const fallbackMessage = data || "Stream error";

  try {
    const parsed = JSON.parse(data) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return new SSEStreamError(fallbackMessage);
    }

    const details = extractStreamErrorDetails(
      parsed as Record<string, unknown>,
      fallbackMessage,
    );
    return new SSEStreamError(details.message, {
      ...details,
      errorCode: normalizeErrorCode(details.errorCode),
    });
  } catch {
    return new SSEStreamError(fallbackMessage);
  }
};

const findSseBoundary = (
  buffer: string,
): { index: number; length: number } | null => {
  const lfBoundary = buffer.indexOf("\n\n");
  const crlfBoundary = buffer.indexOf("\r\n\r\n");

  if (lfBoundary < 0 && crlfBoundary < 0) {
    return null;
  }
  if (lfBoundary < 0) {
    return { index: crlfBoundary, length: 4 };
  }
  if (crlfBoundary < 0) {
    return { index: lfBoundary, length: 2 };
  }

  return lfBoundary < crlfBoundary
    ? { index: lfBoundary, length: 2 }
    : { index: crlfBoundary, length: 4 };
};

const getBackoffDelay = (attempt: number, options: SSEReconnectOptions) => {
  const initialDelayMs = options.initialDelayMs ?? 800;
  const maxDelayMs = options.maxDelayMs ?? 8_000;
  const jitterMs = options.jitterMs ?? 250;
  const baseDelay = Math.min(
    maxDelayMs,
    initialDelayMs * Math.pow(2, Math.max(0, attempt - 1)),
  );
  const jitter = Math.floor(Math.random() * jitterMs);
  return baseDelay + jitter;
};

export const fetchSSE = async (
  url: string,
  handlers: SSEHandlers,
  options: SSEOptions = {},
) => {
  const {
    method = "POST",
    headers = {},
    body,
    signal,
    idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS,
    reconnect,
  } = options;
  const bodyText = body ? JSON.stringify(body) : undefined;
  const maxRetries = reconnect?.retries ?? 0;
  const onlyIfNoData = reconnect?.onlyIfNoData ?? true;

  const runAttempt = async () => {
    let hasReceivedData = false;
    let didTimeout = false;
    let idleTimer: ReturnType<typeof setTimeout> | null = null;

    const controller = new AbortController();
    const handleExternalAbort = () => {
      controller.abort();
    };

    if (signal) {
      if (signal.aborted) {
        controller.abort();
      } else {
        signal.addEventListener("abort", handleExternalAbort);
      }
    }

    const resetIdleTimer = () => {
      if (!idleTimeoutMs) return;
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        didTimeout = true;
        controller.abort();
      }, idleTimeoutMs);
    };

    resetIdleTimer();

    try {
      const requestAuthVersion = useSessionStore.getState().authVersion;
      let token = useSessionStore.getState().token;
      if (token) {
        token = await ensureFreshAccessToken({
          expectedAuthVersion: requestAuthVersion,
        });
      }
      const response = await fetch(url, {
        method,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...headers,
        },
        body: bodyText,
        signal: controller.signal,
      });

      if (isUnauthorizedStatusCode(response.status)) {
        const refreshOutcome = await refreshAccessTokenWithOutcome({
          force: true,
          expectedAuthVersion: requestAuthVersion,
        });
        const refreshed = refreshOutcome.result;
        if (refreshOutcome.didExpireSession) {
          throw new AuthExpiredError();
        }
        if (refreshed) {
          if (useSessionStore.getState().authVersion === requestAuthVersion) {
            useSessionStore
              .getState()
              .setAccessToken(
                refreshed.accessToken,
                refreshed.expiresInSeconds,
              );
          }
          const retryResponse = await fetch(url, {
            method,
            credentials: "include",
            headers: {
              "Content-Type": "application/json",
              Accept: "text/event-stream",
              Authorization: `Bearer ${refreshed.accessToken}`,
              ...headers,
            },
            body: bodyText,
            signal: controller.signal,
          });
          if (isUnauthorizedStatusCode(retryResponse.status)) {
            handleAuthExpiredOnce({
              expectedAuthVersion: requestAuthVersion,
            });
            throw new AuthExpiredError();
          }
          if (!retryResponse.ok) {
            const parsed = await parseApiErrorResponse(retryResponse);
            throw new ApiRequestError(parsed.message, retryResponse.status, {
              errorCode: parsed.errorCode,
              source: parsed.source,
              jsonrpcCode: parsed.jsonrpcCode,
              missingParams: parsed.missingParams,
              upstreamError: parsed.upstreamError,
            });
          }
          await consumeSseStream(retryResponse, handlers, {
            resetIdleTimer,
            markReceivedData: () => {
              hasReceivedData = true;
            },
          });
          return { status: "done" as const, hasReceivedData };
        }
        if (refreshOutcome.failureReason === "transient") {
          throw new AuthRecoverableError();
        }
        handleAuthExpiredOnce({
          expectedAuthVersion: requestAuthVersion,
        });
        throw new AuthExpiredError();
      }

      if (!response.ok) {
        const parsed = await parseApiErrorResponse(response);
        throw new ApiRequestError(parsed.message, response.status, {
          errorCode: parsed.errorCode,
          source: parsed.source,
          jsonrpcCode: parsed.jsonrpcCode,
          missingParams: parsed.missingParams,
          upstreamError: parsed.upstreamError,
        });
      }

      await consumeSseStream(response, handlers, {
        resetIdleTimer,
        markReceivedData: () => {
          hasReceivedData = true;
        },
      });
      return { status: "done" as const, hasReceivedData };
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        if (didTimeout) {
          return {
            status: "error" as const,
            error: new Error(`SSE idle timeout after ${idleTimeoutMs}ms`),
            hasReceivedData,
          };
        }
        return { status: "aborted" as const, hasReceivedData };
      }
      return {
        status: "error" as const,
        error: error instanceof Error ? error : new Error(String(error)),
        hasReceivedData,
      };
    } finally {
      if (idleTimer) clearTimeout(idleTimer);
      if (signal) {
        signal.removeEventListener("abort", handleExternalAbort);
      }
    }
  };

  let attempt = 0;

  while (true) {
    const result = await runAttempt();

    if (result.status === "done") {
      handlers.onDone?.();
      return;
    }

    if (result.status === "aborted") {
      return;
    }

    handlers.onError?.(result.error);

    if (!reconnect || attempt >= maxRetries) {
      return;
    }

    if (onlyIfNoData && result.hasReceivedData) {
      return;
    }

    attempt += 1;
    await sleep(getBackoffDelay(attempt, reconnect));
  }
};

const consumeSseStream = async (
  response: Response,
  handlers: SSEHandlers,
  helpers: {
    resetIdleTimer: () => void;
    markReceivedData: () => void;
  },
): Promise<void> => {
  if (!response.body) {
    throw new Error("Response body is not available for streaming");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    helpers.resetIdleTimer();
    buffer += decoder.decode(value, { stream: true });
    let boundary = findSseBoundary(buffer);
    while (boundary) {
      const rawEvent = buffer.slice(0, boundary.index).trim();
      buffer = buffer.slice(boundary.index + boundary.length);
      boundary = findSseBoundary(buffer);

      if (!rawEvent) continue;

      const event = parseSseEvent(rawEvent);

      if (event.eventType === "error") {
        throw parseSseError(event.data);
      }

      handlers.onEvent?.(event);

      if (event.data) {
        helpers.markReceivedData();
        try {
          const parsed = JSON.parse(event.data);
          if (handlers.onData?.(parsed) === true) {
            return;
          }
        } catch {
          // If not JSON, send as raw content if needed,
          // but usually our backend sends JSON
          if (handlers.onData?.({ content: event.data }) === true) {
            return;
          }
        }
      }

      if (event.eventType === "stream_end") {
        return;
      }
    }
  }
};

const parseSseEvent = (rawEvent: string): SSEEvent => {
  const lines = rawEvent.split(/\r?\n/);
  let eventType = "message";
  const dataLines: string[] = [];

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });

  return { eventType, data: dataLines.join("\n") };
};
