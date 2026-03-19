import { Platform } from "react-native";

import type { A2AAgentInvokeRequest } from "@/lib/api/a2aAgents";
import type { StreamErrorDetails } from "@/lib/api/chat-utils";
import { ENV } from "@/lib/config";
import type { AgentSource } from "@/store/agents";

export type WsConnection = {
  close: (code?: number, reason?: string) => void;
  send: (data: string) => void;
  onopen?: (event?: unknown) => void;
  onmessage?: (event: { data: unknown }) => void;
  onerror?: (event: unknown) => void;
  onclose?: (event: unknown) => void;
  __cancelled?: boolean;
};

export type WsCtor = new (
  url: string,
  protocols?: string | string[],
) => WsConnection;

export type StreamCallbacks = {
  onData: (data: Record<string, unknown>) => boolean | void;
  onDone: () => void;
  onStreamError: (
    message: string,
    details?: Partial<StreamErrorDetails>,
  ) => void;
};

export type TransportParams = {
  conversationId: string;
  agentId: string;
  source: AgentSource;
  payload: A2AAgentInvokeRequest;
  callbacks: StreamCallbacks;
};

export const getWebSocketCtor = () =>
  (globalThis as unknown as { WebSocket?: WsCtor }).WebSocket;

export const supportsWebSocket = typeof getWebSocketCtor() !== "undefined";
export const supportsStreaming =
  Platform.OS === "web" &&
  typeof ReadableStream !== "undefined" &&
  typeof TextDecoder !== "undefined";

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

export const buildInvokeUrl = (
  agentId: string,
  stream: boolean,
  source: AgentSource,
) => {
  const base = ENV.apiBaseUrl.replace(/\/$/, "");
  return `${base}/${scopeForSource(source)}/${encodeURIComponent(agentId)}/invoke${
    stream ? "?stream=true" : ""
  }`;
};

export const buildInvokeWsUrl = (agentId: string, source: AgentSource) => {
  const wsBase = getAbsoluteWsBaseUrl();
  return `${wsBase}/${scopeForSource(source)}/${encodeURIComponent(agentId)}/invoke/ws`;
};
