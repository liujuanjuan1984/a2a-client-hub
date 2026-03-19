import type { A2AAgentInvokeRequest } from "@/lib/api/a2aAgents";
import type { StreamErrorDetails } from "@/lib/api/chat-utils";
import {
  isAuthorizationFailureError,
  isAuthFailureError,
} from "@/lib/api/client";
import { fetchSSE } from "@/lib/api/sse";
import {
  buildInvokeUrl,
  supportsStreaming,
  type StreamCallbacks,
} from "@/services/chatTransportCommon";
import { ChatTransportHealth } from "@/services/chatTransportHealth";
import type { AgentSource } from "@/store/agents";

const streamIdleTimeoutMs = 45_000;

const normalizeErrorCode = (value: unknown): string | null =>
  typeof value === "string" && value.trim().length > 0 ? value.trim() : null;

const extractStructuredErrorCode = (error: unknown): string | null => {
  if (!error || typeof error !== "object") {
    return null;
  }

  const record = error as Record<string, unknown>;
  return normalizeErrorCode(record.errorCode ?? record.error_code);
};

const extractStructuredErrorDetails = (
  error: unknown,
): Partial<StreamErrorDetails> => {
  if (!error || typeof error !== "object") {
    return {};
  }

  const record = error as Record<string, unknown>;
  return {
    errorCode: extractStructuredErrorCode(error),
    source:
      typeof record.source === "string" && record.source.trim().length > 0
        ? record.source.trim()
        : null,
    jsonrpcCode:
      typeof record.jsonrpcCode === "number"
        ? record.jsonrpcCode
        : typeof record.jsonrpc_code === "number"
          ? record.jsonrpc_code
          : null,
    missingParams: Array.isArray(record.missingParams)
      ? (record.missingParams as StreamErrorDetails["missingParams"])
      : Array.isArray(record.missing_params)
        ? (record.missing_params as StreamErrorDetails["missingParams"])
        : null,
    upstreamError:
      record.upstreamError && typeof record.upstreamError === "object"
        ? (record.upstreamError as Record<string, unknown>)
        : record.upstream_error && typeof record.upstream_error === "object"
          ? (record.upstream_error as Record<string, unknown>)
          : null,
  };
};

type SseTransportParams = {
  conversationId: string;
  agentId: string;
  source: AgentSource;
  payload: A2AAgentInvokeRequest;
  callbacks: StreamCallbacks;
  controllers: Map<string, AbortController>;
  health: ChatTransportHealth;
};

export async function trySseTransport({
  conversationId,
  agentId,
  source,
  payload,
  callbacks,
  controllers,
  health,
}: SseTransportParams): Promise<boolean> {
  if (!supportsStreaming) {
    return false;
  }

  const controller = new AbortController();
  controllers.set(conversationId, controller);
  let hasReceivedData = false;

  try {
    await fetchSSE(
      buildInvokeUrl(agentId, true, source),
      {
        onData: (data) => {
          health.recordSseSuccess();
          hasReceivedData = true;
          return callbacks.onData(data);
        },
        onError: (error) => {
          if (!hasReceivedData) {
            throw error;
          }
          callbacks.onStreamError(error.message, {
            ...extractStructuredErrorDetails(error),
            errorCode: extractStructuredErrorCode(error) ?? "stream_error",
          });
        },
        onDone: callbacks.onDone,
      },
      {
        body: payload,
        signal: controller.signal,
        idleTimeoutMs: streamIdleTimeoutMs,
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
    if (isAuthFailureError(error) || isAuthorizationFailureError(error)) {
      throw error;
    }
    health.recordSseFailure(error);
    return false;
  } finally {
    controllers.delete(conversationId);
  }
}
