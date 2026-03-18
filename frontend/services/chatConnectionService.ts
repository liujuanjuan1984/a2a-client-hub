import {
  isAuthorizationFailureError,
  isAuthFailureError,
} from "@/lib/api/client";
import {
  type SessionCancelResult,
  cancelSession as cancelSessionApi,
} from "@/lib/api/sessions";
import { isSessionNotFoundCancellationError } from "@/services/chatConnectionCancellation";
import {
  type TransportParams,
  type WsConnection,
} from "@/services/chatTransportCommon";
import { ChatTransportHealth } from "@/services/chatTransportHealth";
import { trySseTransport } from "@/services/chatTransportSse";
import { tryWebSocketTransport } from "@/services/chatTransportWs";

class ChatConnectionService {
  private readonly abortControllers = new Map<string, AbortController>();
  private readonly wsConnections = new Map<string, WsConnection>();
  private readonly health = new ChatTransportHealth();

  getPreferredTransport() {
    return this.health.getPreferredTransport();
  }

  isWsHealthy() {
    return this.health.isWsHealthy();
  }

  isSseHealthy() {
    return this.health.isSseHealthy();
  }

  hasActiveConnection(conversationId: string): boolean {
    const normalizedConversationId = conversationId.trim();
    if (!normalizedConversationId) {
      return false;
    }
    return (
      this.wsConnections.has(normalizedConversationId) ||
      this.abortControllers.has(normalizedConversationId)
    );
  }

  async cancelSession(
    conversationId: string,
  ): Promise<SessionCancelResult | null> {
    const controller = this.abortControllers.get(conversationId);
    if (controller) {
      controller.abort();
      this.abortControllers.delete(conversationId);
    }

    const ws = this.wsConnections.get(conversationId);
    if (ws) {
      ws.__cancelled = true;
      try {
        ws.close();
      } catch {
        // Ignore close errors.
      }
      this.wsConnections.delete(conversationId);
    }

    const normalizedConversationId = conversationId.trim();
    if (!normalizedConversationId) {
      return null;
    }

    try {
      return await cancelSessionApi(normalizedConversationId);
    } catch (error) {
      if (isAuthFailureError(error) || isAuthorizationFailureError(error)) {
        return null;
      }
      if (isSessionNotFoundCancellationError(error)) {
        return {
          conversationId: normalizedConversationId,
          taskId: null,
          cancelled: false,
          status: "no_inflight",
        };
      }
      console.warn("Failed to request server-side task cancellation", {
        conversationId: normalizedConversationId,
        error,
      });
      return null;
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
    conversationId,
    agentId,
    source,
    payload,
    callbacks,
  }: TransportParams): Promise<boolean> {
    return tryWebSocketTransport({
      conversationId,
      agentId,
      source,
      payload,
      callbacks,
      connections: this.wsConnections,
      health: this.health,
    });
  }

  async trySseTransport({
    conversationId,
    agentId,
    source,
    payload,
    callbacks,
  }: TransportParams): Promise<boolean> {
    return trySseTransport({
      conversationId,
      agentId,
      source,
      payload,
      callbacks,
      controllers: this.abortControllers,
      health: this.health,
    });
  }
}

export const chatConnectionService = new ChatConnectionService();
