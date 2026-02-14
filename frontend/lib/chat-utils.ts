import type { A2AAgentInvokeRequest } from "@/lib/api/a2aAgents";

export type ExternalSessionRef = {
  provider?: string | null;
  externalSessionId?: string | null;
  contextId?: string | null;
  bindingMetadata?: Record<string, unknown>;
};

export type AgentSession = {
  agentId: string;
  conversationId?: string | null;
  contextId: string | null;
  runtimeStatus?: string | null;
  streamState?: "idle" | "streaming" | "rebinding" | "recoverable" | "error";
  lastStreamError?: string | null;
  transport: string;
  inputModes: string[];
  outputModes: string[];
  metadata: Record<string, unknown>;
  externalSessionRef?: ExternalSessionRef | null;
  lastActiveAt: string;
};

const FALLBACK_LAST_ACTIVE_AT = "1970-01-01T00:00:00.000Z";
const SESSION_TTL_MS = 14 * 24 * 60 * 60 * 1000;

export const createAgentSession = (agentId: string): AgentSession => ({
  agentId,
  contextId: null,
  runtimeStatus: null,
  streamState: "idle",
  lastStreamError: null,
  transport: "http_json",
  inputModes: ["text/plain"],
  outputModes: ["text/plain"],
  metadata: {},
  conversationId: null,
  externalSessionRef: null,
  lastActiveAt: new Date().toISOString(),
});

export const mergeExternalSessionRef = (
  current: ExternalSessionRef | null | undefined,
  incoming: {
    provider?: string | null;
    externalSessionId?: string | null;
    contextId?: string | null;
    bindingMetadata?: Record<string, unknown> | null;
  },
): ExternalSessionRef => ({
  provider: incoming.provider ?? current?.provider ?? null,
  externalSessionId:
    incoming.externalSessionId ?? current?.externalSessionId ?? null,
  contextId: incoming.contextId ?? current?.contextId ?? null,
  bindingMetadata: incoming.bindingMetadata ?? current?.bindingMetadata ?? {},
});

export const buildInvokePayload = (
  query: string,
  session: AgentSession,
  sessionId: string,
): A2AAgentInvokeRequest => {
  const payload: A2AAgentInvokeRequest = { query, sessionId };
  if (session.contextId) {
    payload.contextId = session.contextId;
  }
  if (Object.keys(session.metadata).length > 0) {
    payload.metadata = session.metadata;
  }
  return payload;
};

const getSessionLastActiveAt = (session: AgentSession) =>
  typeof session.lastActiveAt === "string"
    ? session.lastActiveAt
    : FALLBACK_LAST_ACTIVE_AT;

export const sortSessionsByLastActive = (
  sessions: [string, AgentSession][],
): [string, AgentSession][] =>
  [...sessions].sort((a, b) =>
    getSessionLastActiveAt(b[1]).localeCompare(getSessionLastActiveAt(a[1])),
  );

export const buildSessionCleanupPlan = (
  sessions: Record<string, AgentSession>,
  messageSessionIds: string[],
  now: Date = new Date(),
) => {
  const deadline = new Date(now.getTime() - SESSION_TTL_MS).toISOString();
  const nextSessions = { ...sessions };
  const expiredSessionIds: string[] = [];

  Object.entries(sessions).forEach(([sessionId, session]) => {
    if (session.lastActiveAt < deadline) {
      delete nextSessions[sessionId];
      expiredSessionIds.push(sessionId);
    }
  });

  const orphanedMessageSessionIds = messageSessionIds.filter(
    (sessionId) => !nextSessions[sessionId],
  );
  const changed =
    expiredSessionIds.length > 0 || orphanedMessageSessionIds.length > 0;

  return {
    sessions: nextSessions,
    expiredSessionIds,
    orphanedMessageSessionIds,
    changed,
  };
};
