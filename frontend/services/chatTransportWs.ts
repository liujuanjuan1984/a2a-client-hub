import {
  getInvokeWsTicket,
  type A2AAgentInvokeRequest,
} from "@/lib/api/a2aAgents";
import {
  isAuthorizationFailureError,
  isAuthFailureError,
} from "@/lib/api/client";
import { getHubInvokeWsTicket } from "@/lib/api/hubA2aAgentsUser";
import {
  buildInvokeWsUrl,
  getWebSocketCtor,
  supportsWebSocket,
  type StreamCallbacks,
  type WsConnection,
} from "@/services/chatTransportCommon";
import { ChatTransportHealth } from "@/services/chatTransportHealth";
import type { AgentSource } from "@/store/agents";

const wsConnectTimeoutMs = 10_000;
const wsIdleTimeoutMs = 45_000;

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

type WebSocketTransportParams = {
  conversationId: string;
  agentId: string;
  source: AgentSource;
  payload: A2AAgentInvokeRequest;
  callbacks: StreamCallbacks;
  connections: Map<string, WsConnection>;
  health: ChatTransportHealth;
};

export async function tryWebSocketTransport({
  conversationId,
  agentId,
  source,
  payload,
  callbacks,
  connections,
  health,
}: WebSocketTransportParams): Promise<boolean> {
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

      const ws = new WebSocketCtor(wsUrl, ["a2a-invoke-v1", ticket.token]);
      connections.set(conversationId, ws);

      const cleanup = () => {
        if (connectTimer) {
          clearTimeout(connectTimer);
          connectTimer = null;
        }
        if (idleTimer) {
          clearTimeout(idleTimer);
          idleTimer = null;
        }
        connections.delete(conversationId);
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
          if (hasReceivedData) {
            callbacks.onStreamError(
              `WebSocket idle timeout after ${wsIdleTimeoutMs}ms`,
              { errorCode: "timeout" },
            );
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
        health.recordWsSuccess();
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
          .catch((error) => {
            console.error("WebSocket message resolve error:", error);
            finalize(
              "reject",
              error instanceof Error ? error : new Error(String(error)),
            );
          });
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
        callbacks.onStreamError("WebSocket error", {
          errorCode: "stream_error",
        });
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
        callbacks.onStreamError("WebSocket closed unexpectedly", {
          errorCode: "stream_closed",
        });
        finalize("resolve");
      };

      connectTimer = setTimeout(() => {
        if (settled) return;
        finalize("reject", new Error("WebSocket connection timeout"));
      }, wsConnectTimeoutMs);
    });
    return true;
  } catch (error) {
    if (isAuthFailureError(error) || isAuthorizationFailureError(error)) {
      throw error;
    }
    health.recordWsFailure(error);
    return false;
  }
}
