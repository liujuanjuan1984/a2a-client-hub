import { Platform } from "react-native";

import {
  getInvokeWsTicket,
  type A2AAgentInvokeRequest,
} from "@/lib/api/a2aAgents";
import { getHubInvokeWsTicket } from "@/lib/api/hubA2aAgentsUser";
import { fetchSSE } from "@/lib/api/sse";
import { ENV } from "@/lib/config";
import type { AgentSource } from "@/store/agents";

type WsConnection = {
  close: (code?: number, reason?: string) => void;
  send: (data: string) => void;
  onopen?: (event?: unknown) => void;
  onmessage?: (event: { data: unknown }) => void;
  onerror?: (event: unknown) => void;
  onclose?: (event: unknown) => void;
  __cancelled?: boolean;
};

type WsCtor = new (url: string, protocols?: string | string[]) => WsConnection;

const getWebSocketCtor = () =>
  (globalThis as unknown as { WebSocket?: WsCtor }).WebSocket;

const supportsWebSocket = typeof getWebSocketCtor() !== "undefined";
const supportsStreaming =
  Platform.OS === "web" &&
  typeof ReadableStream !== "undefined" &&
  typeof TextDecoder !== "undefined";

const wsConnectTimeoutMs = 10_000;
const wsIdleTimeoutMs = 45_000;

const isAbsoluteHttpUrl = (value: string) => /^https?:\/\//.test(value);

const getAbsoluteApiBaseUrl = () => {
  const base = ENV.apiBaseUrl.replace(/\/$/, "");
  if (isAbsoluteHttpUrl(base)) return base;

  if (Platform.OS === "web" && typeof window !== "undefined") {
    return new URL(base, window.location.origin).toString().replace(/\/$/, "");
  }

  return base;
};

const getAbsoluteWsBaseUrl = () => {
  const httpBase = getAbsoluteApiBaseUrl();
  if (!isAbsoluteHttpUrl(httpBase)) {
    throw new Error(
      `WebSocket requires an absolute EXPO_PUBLIC_API_BASE_URL on ${Platform.OS}.`,
    );
  }
  return httpBase.replace(/^http/, "ws");
};

const scopeForSource = (source: AgentSource) =>
  source === "shared" ? "a2a/agents" : "me/a2a/agents";

const buildInvokeUrl = (
  agentId: string,
  stream: boolean,
  source: AgentSource,
) => {
  const base = ENV.apiBaseUrl.replace(/\/$/, "");
  return `${base}/${scopeForSource(source)}/${encodeURIComponent(agentId)}/invoke${
    stream ? "?stream=true" : ""
  }`;
};

const buildInvokeWsUrl = (agentId: string, source: AgentSource) => {
  const wsBase = getAbsoluteWsBaseUrl();
  return `${wsBase}/${scopeForSource(source)}/${encodeURIComponent(agentId)}/invoke/ws`;
};

type StreamCallbacks = {
  onData: (data: Record<string, unknown>) => boolean | void;
  onDone: () => void;
  onStreamError: (message: string) => void;
};

type TransportParams = {
  sessionId: string;
  agentId: string;
  source: AgentSource;
  payload: A2AAgentInvokeRequest;
  callbacks: StreamCallbacks;
};

const resolveWsText = async (data: unknown): Promise<string | null> => {
  if (typeof data === "string") return data;
  if (
    typeof Blob !== "undefined" &&
    data instanceof Blob &&
    typeof data.text === "function"
  ) {
    try {
      return await data.text();
    } catch {
      return null;
    }
  }
  if (data instanceof ArrayBuffer && typeof TextDecoder !== "undefined") {
    return new TextDecoder().decode(data);
  }
  return null;
};

export class ChatConnectionService {
  private readonly abortControllers = new Map<string, AbortController>();
  private readonly wsConnections = new Map<string, WsConnection>();

  getPreferredTransport() {
    if (supportsWebSocket) return "ws";
    if (supportsStreaming) return "http_sse";
    return "http_json";
  }

  cancelSession(sessionId: string) {
    const controller = this.abortControllers.get(sessionId);
    if (controller) {
      controller.abort();
      this.abortControllers.delete(sessionId);
    }

    const ws = this.wsConnections.get(sessionId);
    if (ws) {
      ws.__cancelled = true;
      try {
        ws.close();
      } catch {
        // Ignore close errors.
      }
      this.wsConnections.delete(sessionId);
    }
  }

  migrateSessionKey(fromSessionId: string, toSessionId: string) {
    const fromKey = fromSessionId.trim();
    const toKey = toSessionId.trim();
    if (!fromKey || !toKey || fromKey === toKey) return;

    const controller = this.abortControllers.get(fromKey);
    if (controller) {
      if (!this.abortControllers.has(toKey)) {
        this.abortControllers.set(toKey, controller);
      }
      this.abortControllers.delete(fromKey);
    }

    const ws = this.wsConnections.get(fromKey);
    if (ws) {
      const existing = this.wsConnections.get(toKey);
      if (!existing) {
        this.wsConnections.set(toKey, ws);
      } else {
        try {
          ws.__cancelled = true;
          ws.close();
        } catch {
          // Ignore close errors.
        }
      }
      this.wsConnections.delete(fromKey);
    }
  }

  clearAll() {
    this.wsConnections.forEach((ws) => {
      try {
        ws.__cancelled = true;
        ws.close();
      } catch {
        // Ignore close errors.
      }
    });
    this.abortControllers.forEach((controller) => {
      try {
        controller.abort();
      } catch {
        // Ignore abort errors.
      }
    });
    this.wsConnections.clear();
    this.abortControllers.clear();
  }

  async tryWebSocketTransport({
    sessionId,
    agentId,
    source,
    payload,
    callbacks,
  }: TransportParams): Promise<boolean> {
    if (!supportsWebSocket) {
      return false;
    }

    try {
      const ticket =
        source === "shared"
          ? await getHubInvokeWsTicket(agentId)
          : await getInvokeWsTicket(agentId);
      const wsUrl = buildInvokeWsUrl(agentId, source);
      const WebSocketCtor = getWebSocketCtor();
      if (!WebSocketCtor) {
        throw new Error("WebSocket is not available");
      }

      await new Promise<void>((resolve, reject) => {
        let hasReceivedData = false;
        let settled = false;
        let closed = false;
        let connectTimer: ReturnType<typeof setTimeout> | null = null;
        let idleTimer: ReturnType<typeof setTimeout> | null = null;

        const ws = new WebSocketCtor(wsUrl, [ticket.token]);
        this.wsConnections.set(sessionId, ws);

        const cleanup = () => {
          if (connectTimer) {
            clearTimeout(connectTimer);
            connectTimer = null;
          }
          if (idleTimer) {
            clearTimeout(idleTimer);
            idleTimer = null;
          }
          this.wsConnections.delete(sessionId);
        };

        const finalize = (mode: "resolve" | "reject", error?: Error) => {
          if (settled) return;
          settled = true;
          if (!closed) {
            try {
              ws.close();
            } catch {
              // Ignore close errors.
            }
          }
          cleanup();
          if (mode === "resolve") {
            resolve();
            return;
          }
          reject(error ?? new Error("WebSocket failed"));
        };

        const resetIdleTimer = () => {
          if (idleTimer) {
            clearTimeout(idleTimer);
          }
          idleTimer = setTimeout(() => {
            if (settled) return;
            if (ws.__cancelled) {
              finalize("resolve");
              return;
            }
            finalize("reject", new Error("WebSocket idle timeout"));
          }, wsIdleTimeoutMs);
        };

        ws.onopen = () => {
          if (connectTimer) {
            clearTimeout(connectTimer);
            connectTimer = null;
          }
          resetIdleTimer();
          ws.send(JSON.stringify(payload));
        };

        ws.onmessage = (event) => {
          if (settled) return;
          resetIdleTimer();
          resolveWsText(event.data)
            .then((text) => {
              if (!text || settled) return;
              let data: Record<string, unknown> | null = null;
              try {
                data = JSON.parse(text) as Record<string, unknown>;
              } catch {
                return;
              }
              hasReceivedData = true;
              const shouldResolve = callbacks.onData(data) === true;
              if (shouldResolve) {
                finalize("resolve");
              }
            })
            .catch(() => undefined);
        };

        ws.onerror = () => {
          if (settled) return;
          if (ws.__cancelled) {
            finalize("resolve");
            return;
          }
          if (!hasReceivedData) {
            finalize("reject", new Error("WebSocket connection failed"));
            return;
          }
          callbacks.onStreamError("WebSocket error");
          finalize("resolve");
        };

        ws.onclose = () => {
          closed = true;
          if (settled) return;
          if (ws.__cancelled) {
            finalize("resolve");
            return;
          }
          if (!hasReceivedData) {
            finalize(
              "reject",
              new Error("WebSocket closed before receiving data"),
            );
            return;
          }
          callbacks.onDone();
          finalize("resolve");
        };

        connectTimer = setTimeout(() => {
          if (settled) return;
          finalize("reject", new Error("WebSocket connection timeout"));
        }, wsConnectTimeoutMs);
      });
      return true;
    } catch (error) {
      console.warn("[WS Fallback]", {
        platform: Platform.OS,
        reason: error instanceof Error ? error.message : String(error),
      });
      return false;
    }
  }

  async trySseTransport({
    sessionId,
    agentId,
    source,
    payload,
    callbacks,
  }: TransportParams): Promise<boolean> {
    if (!supportsStreaming) {
      return false;
    }

    const controller = new AbortController();
    this.abortControllers.set(sessionId, controller);
    let hasReceivedData = false;

    try {
      await fetchSSE(
        buildInvokeUrl(agentId, true, source),
        {
          onData: (data) => {
            hasReceivedData = true;
            return callbacks.onData(data);
          },
          onError: (error) => {
            if (!hasReceivedData) {
              throw error;
            }
            callbacks.onStreamError(error.message);
          },
          onDone: callbacks.onDone,
        },
        {
          body: payload,
          signal: controller.signal,
          idleTimeoutMs: wsIdleTimeoutMs,
          reconnect: {
            retries: 2,
            initialDelayMs: 800,
            maxDelayMs: 8_000,
            jitterMs: 250,
            onlyIfNoData: true,
          },
        },
      );
      return true;
    } catch (error) {
      console.warn("[SSE Fallback]", {
        platform: Platform.OS,
        reason: error instanceof Error ? error.message : String(error),
      });
      return false;
    } finally {
      this.abortControllers.delete(sessionId);
    }
  }
}

export const chatConnectionService = new ChatConnectionService();
