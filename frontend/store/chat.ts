import { Platform } from "react-native";
import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  getInvokeWsTicket,
  type A2AAgentInvokeRequest,
  invokeAgent,
} from "@/lib/api/a2aAgents";
import {
  extractRuntimeStatus,
  extractSessionMeta,
  type StreamChunk,
  extractStreamChunk,
} from "@/lib/api/chat-utils";
import {
  getHubInvokeWsTicket,
  invokeHubAgent,
} from "@/lib/api/hubA2aAgentsUser";
import { fetchSSE } from "@/lib/api/sse";
import { ENV } from "@/lib/config";
import { generateId } from "@/lib/id";
import { createPersistStorage } from "@/lib/storage/mmkv";
import { applyStreamChunk } from "@/lib/streamChunks";
import { shouldSplitStreamMessage } from "@/lib/streamMessageSplit";
import { type AgentSource, useAgentStore } from "@/store/agents";
import { useMessageStore } from "@/store/messages";

export type AgentSession = {
  agentId: string;
  contextId: string | null;
  runtimeStatus?: string | null;
  transport: string;
  inputModes: string[];
  outputModes: string[];
  metadata: Record<string, unknown>;
  opencodeSessionId?: string | null;
  lastActiveAt: string;
};

export type ChatState = {
  sessions: Record<string, AgentSession>;
  abortControllers: Record<string, AbortController>;
  wsConnections: Record<string, WsConnection>;
  ensureSession: (sessionId: string, agentId: string) => void;
  sendMessage: (
    sessionId: string,
    agentId: string,
    content: string,
  ) => Promise<void>;
  cancelMessage: (sessionId: string) => void;
  resetSession: (sessionId: string, agentId: string) => void;
  bindOpencodeSession: (
    sessionId: string,
    payload: {
      agentId: string;
      opencodeSessionId: string;
      contextId?: string | null;
      metadata?: Record<string, unknown> | null;
    },
  ) => void;
  getSessionsByAgentId: (agentId: string) => [string, AgentSession][];
  getLatestSessionIdByAgentId: (agentId: string) => string | undefined;
  cleanupSessions: () => void;
  generateSessionId: () => string;
};

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

const createSession = (agentId: string): AgentSession => ({
  agentId,
  contextId: null,
  runtimeStatus: null,
  transport: "http_json",
  inputModes: ["text/plain"],
  outputModes: ["text/plain"],
  metadata: {},
  opencodeSessionId: null,
  lastActiveAt: new Date().toISOString(),
});

const isIOSWeb =
  Platform.OS === "web" &&
  typeof navigator !== "undefined" &&
  typeof window !== "undefined" &&
  /iPad|iPhone|iPod/.test(navigator.userAgent) &&
  !(window as any).MSStream;

const supportsStreaming =
  Platform.OS === "web" &&
  typeof ReadableStream !== "undefined" &&
  typeof TextDecoder !== "undefined"; // Enable streaming on web when supported (including iOS Web)

const supportsWebSocket = typeof getWebSocketCtor() !== "undefined";
const wsConnectTimeoutMs = 10_000;
const wsIdleTimeoutMs = 45_000;

const isAbsoluteHttpUrl = (value: string) => /^https?:\/\//.test(value);

const getAbsoluteApiBaseUrl = () => {
  const base = ENV.apiBaseUrl.replace(/\/$/, "");
  if (isAbsoluteHttpUrl(base)) return base;

  // Web supports same-origin relative API bases like `/api/v1`.
  if (Platform.OS === "web" && typeof window !== "undefined") {
    return new URL(base, window.location.origin).toString().replace(/\/$/, "");
  }

  // Native does not have an origin; relative API bases are invalid.
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

const resolveAgentSource = (agentId: string): AgentSource => {
  const agent = useAgentStore
    .getState()
    .agents.find((item) => item.id === agentId);
  return agent?.source ?? "personal";
};

const buildInvokePayload = (
  query: string,
  session: AgentSession,
): A2AAgentInvokeRequest => {
  const payload: A2AAgentInvokeRequest = { query };
  if (session.contextId) {
    payload.contextId = session.contextId;
  }
  if (Object.keys(session.metadata).length > 0) {
    payload.metadata = session.metadata;
  }
  return payload;
};

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: {},
      abortControllers: {},
      wsConnections: {},
      ensureSession: (sessionId, agentId) => {
        set((state) => {
          if (state.sessions[sessionId]) {
            return {
              sessions: {
                ...state.sessions,
                [sessionId]: {
                  ...state.sessions[sessionId],
                  lastActiveAt: new Date().toISOString(),
                },
              },
            };
          }
          return {
            sessions: {
              ...state.sessions,
              [sessionId]: createSession(agentId),
            },
          };
        });
      },
      bindOpencodeSession: (sessionId, payload) => {
        set((state) => ({
          sessions: {
            ...state.sessions,
            [sessionId]: {
              ...(state.sessions[sessionId] ?? createSession(payload.agentId)),
              agentId: payload.agentId,
              opencodeSessionId: payload.opencodeSessionId,
              contextId:
                payload.contextId === undefined
                  ? (state.sessions[sessionId]?.contextId ?? null)
                  : payload.contextId,
              metadata: payload.metadata ?? {},
              lastActiveAt: new Date().toISOString(),
            },
          },
        }));
      },
      resetSession: (sessionId, agentId) => {
        get().cancelMessage(sessionId);
        set((state) => ({
          sessions: {
            ...state.sessions,
            [sessionId]: createSession(agentId),
          },
        }));
        useMessageStore.getState().removeMessages(sessionId);
      },
      cancelMessage: (sessionId) => {
        const controller = get().abortControllers[sessionId];
        if (controller) {
          controller.abort();
          set((state) => {
            const next = { ...state.abortControllers };
            delete next[sessionId];
            return { abortControllers: next };
          });
        }
        const ws = get().wsConnections[sessionId];
        if (ws) {
          ws.__cancelled = true;
          ws.close();
          set((state) => {
            const next = { ...state.wsConnections };
            delete next[sessionId];
            return { wsConnections: next };
          });
        }
      },
      sendMessage: async (sessionId, agentId, content) => {
        const trimmed = content.trim();
        if (!trimmed) return;

        // Cancel any pending request for this session
        get().cancelMessage(sessionId);

        const userMessage = {
          id: generateId(),
          role: "user" as const,
          content: trimmed,
          createdAt: new Date().toISOString(),
          status: "done" as const,
        };

        const agentMessageId = generateId();
        const agentMessage = {
          id: agentMessageId,
          role: "agent" as const,
          content: "",
          streamChunks: [],
          createdAt: new Date().toISOString(),
          status: "streaming" as const,
        };

        set((state) => ({
          sessions: {
            ...state.sessions,
            [sessionId]: {
              ...(state.sessions[sessionId] ?? createSession(agentId)),
              lastActiveAt: new Date().toISOString(),
              transport: supportsWebSocket
                ? "ws"
                : supportsStreaming
                  ? "http_sse"
                  : "http_json",
            },
          },
        }));

        const messageStore = useMessageStore.getState();
        messageStore.addMessage(sessionId, userMessage);
        messageStore.addMessage(sessionId, agentMessage);

        let activeAgentMessageId = agentMessageId;

        const session = get().sessions[sessionId] ?? createSession(agentId);
        const payload = buildInvokePayload(trimmed, session);
        const agentSource = resolveAgentSource(agentId);

        const updateSessionMeta = (meta: {
          contextId?: string | null;
          runtimeStatus?: string | null;
          transport?: string;
          inputModes?: string[];
          outputModes?: string[];
        }) => {
          set((state) => {
            const current = state.sessions[sessionId];
            if (!current) return state;
            return {
              sessions: {
                ...state.sessions,
                [sessionId]: {
                  ...current,
                  ...meta,
                  contextId: meta.contextId ?? current.contextId,
                },
              },
            };
          });
        };

        const appendStreamChunk = (chunk: StreamChunk) => {
          const bucket = useMessageStore.getState().messages[sessionId] || [];
          const current = bucket.find((m) => m.id === activeAgentMessageId);
          if (!current) return;

          if (shouldSplitStreamMessage(current, chunk)) {
            // Finish the current streamed message and start a new one.
            messageStore.updateMessage(sessionId, activeAgentMessageId, {
              status: "done",
            });
            const nextAgentMessageId = generateId();
            activeAgentMessageId = nextAgentMessageId;
            messageStore.addMessage(sessionId, {
              id: nextAgentMessageId,
              role: "agent" as const,
              content: "",
              streamChunks: [],
              createdAt: new Date().toISOString(),
              status: "streaming" as const,
            });
          }

          const targetId = activeAgentMessageId;
          messageStore.updateMessageWithUpdater(
            sessionId,
            targetId,
            (message) => {
              const next = applyStreamChunk(
                message.content,
                message.streamChunks,
                chunk,
              );
              return {
                content: next.content,
                streamChunks: next.streamChunks,
                status: chunk.done ? "done" : "streaming",
              };
            },
          );
        };

        const appendStreamError = (errorText: string) => {
          messageStore.updateMessageWithUpdater(
            sessionId,
            activeAgentMessageId,
            (message) => ({
              content: `${message.content}\n[Stream Error: ${errorText}]`,
              status: "done",
            }),
          );
        };

        if (supportsWebSocket) {
          try {
            const ticket =
              agentSource === "shared"
                ? await getHubInvokeWsTicket(agentId)
                : await getInvokeWsTicket(agentId);
            const wsUrl = buildInvokeWsUrl(agentId, agentSource);
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

              // Use Sec-WebSocket-Protocol to avoid exposing ticket in URL.
              const ws = new WebSocketCtor(wsUrl, [ticket.token]);
              set((state) => ({
                wsConnections: {
                  ...state.wsConnections,
                  [sessionId]: ws,
                },
              }));

              const cleanup = () => {
                if (connectTimer) {
                  clearTimeout(connectTimer);
                  connectTimer = null;
                }
                if (idleTimer) {
                  clearTimeout(idleTimer);
                  idleTimer = null;
                }
                set((state) => {
                  const next = { ...state.wsConnections };
                  delete next[sessionId];
                  return { wsConnections: next };
                });
              };

              const finalize = (mode: "resolve" | "reject", error?: Error) => {
                if (settled) return;
                settled = true;
                if (!closed) {
                  try {
                    ws.close();
                  } catch {
                    // Ignore close errors
                  }
                }
                cleanup();
                if (mode === "resolve") {
                  resolve();
                } else {
                  reject(error ?? new Error("WebSocket failed"));
                }
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

              const handleMessageText = (raw: string) => {
                if (settled) return;
                if (!raw) return;
                hasReceivedData = true;
                resetIdleTimer();

                let data: Record<string, unknown> | null = null;
                try {
                  data = JSON.parse(raw) as Record<string, unknown>;
                } catch {
                  return;
                }

                if (data.event === "error") {
                  const message =
                    typeof (data.data as { message?: unknown } | undefined)
                      ?.message === "string"
                      ? (data.data as { message: string }).message
                      : "Stream error.";
                  appendStreamError(message);
                  finalize("resolve");
                  return;
                }

                if (data.event === "stream_end") {
                  messageStore.updateMessage(sessionId, activeAgentMessageId, {
                    status: "done",
                  });
                  finalize("resolve");
                  return;
                }

                const chunk = extractStreamChunk(data);
                if (chunk) {
                  appendStreamChunk(chunk);
                }

                const meta = extractSessionMeta(data);
                const runtimeStatus = extractRuntimeStatus(data);
                if (
                  meta.contextId ||
                  meta.transport ||
                  meta.inputModes ||
                  meta.outputModes ||
                  runtimeStatus
                ) {
                  updateSessionMeta({ ...meta, runtimeStatus });
                }
              };

              ws.onopen = () => {
                if (connectTimer) {
                  clearTimeout(connectTimer);
                  connectTimer = null;
                }
                resetIdleTimer();
                ws.send(JSON.stringify(payload));
              };

              ws.onmessage = async (event) => {
                if (settled) return;
                const { data } = event;
                if (typeof data === "string") {
                  handleMessageText(data);
                  return;
                }
                if (
                  typeof Blob !== "undefined" &&
                  data instanceof Blob &&
                  typeof data.text === "function"
                ) {
                  try {
                    const text = await data.text();
                    handleMessageText(text);
                  } catch {
                    // Ignore parse errors
                  }
                  return;
                }
                if (
                  data instanceof ArrayBuffer &&
                  typeof TextDecoder !== "undefined"
                ) {
                  const text = new TextDecoder().decode(data);
                  handleMessageText(text);
                }
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
                appendStreamError("WebSocket error");
                finalize("resolve");
              };

              ws.onclose = () => {
                closed = true;
                if (!settled) {
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
                  finalize("resolve");
                }
              };

              connectTimer = setTimeout(() => {
                if (settled) return;
                finalize("reject", new Error("WebSocket connection timeout"));
              }, wsConnectTimeoutMs);
            });
            return;
          } catch (error) {
            console.warn("[WS Fallback]", {
              platform: Platform.OS,
              reason: error instanceof Error ? error.message : String(error),
            });
          }
        }

        if (supportsStreaming) {
          updateSessionMeta({ transport: "http_sse" });
          const controller = new AbortController();
          set((state) => ({
            abortControllers: {
              ...state.abortControllers,
              [sessionId]: controller,
            },
          }));

          let hasReceivedData = false;

          try {
            await fetchSSE(
              buildInvokeUrl(agentId, true, agentSource),
              {
                onData: (data) => {
                  hasReceivedData = true;
                  const chunk = extractStreamChunk(data);
                  if (chunk) {
                    appendStreamChunk(chunk);
                  }
                  const meta = extractSessionMeta(data);
                  const runtimeStatus = extractRuntimeStatus(data);
                  if (
                    meta.contextId ||
                    meta.transport ||
                    meta.inputModes ||
                    meta.outputModes ||
                    runtimeStatus
                  ) {
                    updateSessionMeta({ ...meta, runtimeStatus });
                  }
                },
                onError: (error) => {
                  console.error("[SSE Error]", {
                    platform: Platform.OS,
                    isIOSWeb,
                    message: error.message,
                  });

                  // If we haven't received any data yet, we can try to fallback
                  if (!hasReceivedData) {
                    throw error; // Catch and fallback
                  } else {
                    // Already partial data, just mark as done with error
                    appendStreamError(error.message);
                  }
                },
                onDone: () => {
                  messageStore.updateMessage(sessionId, activeAgentMessageId, {
                    status: "done",
                  });
                  set((state) => {
                    const next = { ...state.abortControllers };
                    delete next[sessionId];
                    return { abortControllers: next };
                  });
                },
              },
              {
                body: payload,
                signal: controller.signal,
                idleTimeoutMs: 45_000,
                reconnect: {
                  retries: 2,
                  initialDelayMs: 800,
                  maxDelayMs: 8_000,
                  jitterMs: 250,
                  onlyIfNoData: true,
                },
              },
            );
            return;
          } catch (error) {
            console.warn("[SSE Fallback]", {
              platform: Platform.OS,
              isIOSWeb,
              reason: error instanceof Error ? error.message : String(error),
            });
            // Fall through to non-streaming logic
          }
        }

        // Fallback to non-streaming
        try {
          updateSessionMeta({ transport: "http_json" });
          const response =
            agentSource === "shared"
              ? await invokeHubAgent(agentId, payload)
              : await invokeAgent(agentId, payload);
          if (!response.success) {
            const message =
              response.error || response.error_code || "Request failed.";
            messageStore.updateMessage(sessionId, agentMessageId, {
              content: message,
              status: "done",
            });
            return;
          }

          messageStore.updateMessage(sessionId, agentMessageId, {
            content: response.content ?? "",
            status: "done",
          });
        } catch (error) {
          const message =
            error instanceof Error ? error.message : "Request failed.";
          messageStore.updateMessage(sessionId, agentMessageId, {
            content: message,
            status: "done",
          });
        }
      },
      getSessionsByAgentId: (agentId) => {
        const getLastActiveAt = (session: AgentSession) =>
          typeof session.lastActiveAt === "string"
            ? session.lastActiveAt
            : "1970-01-01T00:00:00.000Z";
        return Object.entries(get().sessions)
          .filter(([_, s]) => s.agentId === agentId)
          .sort((a, b) =>
            getLastActiveAt(b[1]).localeCompare(getLastActiveAt(a[1])),
          );
      },
      getLatestSessionIdByAgentId: (agentId) => {
        const sessions = get().getSessionsByAgentId(agentId);
        return sessions[0]?.[0];
      },
      cleanupSessions: () => {
        const now = new Date();
        const deadline = new Date(
          now.getTime() - 14 * 24 * 60 * 60 * 1000,
        ).toISOString();

        set((state) => {
          const nextSessions = { ...state.sessions };
          let changed = false;

          // 1. Clean up by expiration
          Object.entries(state.sessions).forEach(([id, session]) => {
            if (session.lastActiveAt < deadline) {
              delete nextSessions[id];
              useMessageStore.getState().removeMessages(id);
              changed = true;
            }
          });

          // 2. Orphaned messages cleanup (Self-healing)
          // Ensure every message bucket has a corresponding session meta
          const messageStore = useMessageStore.getState();
          const messageSessionIds = Object.keys(messageStore.messages);
          messageSessionIds.forEach((id) => {
            if (!nextSessions[id]) {
              messageStore.removeMessages(id);
            }
          });

          return changed ? { sessions: nextSessions } : state;
        });
      },
      generateSessionId: () => generateId("sess"),
    }),
    {
      name: "a2a-client-hub.chat",
      storage: createPersistStorage(),
      partialize: (state) => ({
        sessions: state.sessions,
      }),
    },
  ),
);
