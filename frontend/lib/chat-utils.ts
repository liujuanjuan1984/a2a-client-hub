import type { A2AAgentInvokeRequest } from "@/lib/api/a2aAgents";

export type ExternalSessionRef = {
  provider?: string | null;
  externalSessionId?: string | null;
};

export type AgentSession = {
  agentId: string;
  source?: "manual" | "scheduled" | "opencode" | null;
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
export const CHAT_SESSION_TTL_MS = 14 * 24 * 60 * 60 * 1000;
export const CHAT_SESSION_MAX_ACTIVE = 240;
export const CHAT_SESSION_MAX_PERSISTED = 80;

export const createAgentSession = (agentId: string): AgentSession => ({
  agentId,
  source: null,
  contextId: null,
  runtimeStatus: null,
  streamState: "idle",
  lastStreamError: null,
  transport: "http_json",
  inputModes: ["text/plain"],
  outputModes: ["text/plain"],
  metadata: {},
  externalSessionRef: null,
  lastActiveAt: new Date().toISOString(),
});

export const mergeExternalSessionRef = (
  current: ExternalSessionRef | null | undefined,
  incoming: {
    provider?: string | null;
    externalSessionId?: string | null;
  },
): ExternalSessionRef => ({
  provider: incoming.provider ?? current?.provider ?? null,
  externalSessionId:
    incoming.externalSessionId ?? current?.externalSessionId ?? null,
});

export const buildInvokePayload = (
  query: string,
  session: AgentSession,
  conversationId: string,
  options?: {
    userMessageId?: string;
    clientAgentMessageId?: string;
  },
): A2AAgentInvokeRequest => {
  const payload: A2AAgentInvokeRequest = { query, conversationId };
  if (options?.userMessageId) {
    payload.userMessageId = options.userMessageId;
  }
  if (options?.clientAgentMessageId) {
    payload.clientAgentMessageId = options.clientAgentMessageId;
  }
  if (session.contextId) {
    payload.contextId = session.contextId;
  }
  const metadata: Record<string, unknown> = { ...(session.metadata ?? {}) };
  const externalProvider = session.externalSessionRef?.provider
    ?.trim()
    .toLowerCase();
  const externalSessionId =
    session.externalSessionRef?.externalSessionId?.trim();
  if (externalProvider === "opencode" && externalSessionId) {
    // Upstream opencode-a2a-serve requires this explicit key to continue a session.
    metadata.opencode_session_id = externalSessionId;
  }
  if (Object.keys(metadata).length > 0) {
    payload.metadata = metadata;
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

const normalizeSessionForPersistence = (
  session: AgentSession,
): AgentSession => ({
  agentId: session.agentId,
  source: session.source ?? null,
  contextId: session.contextId ?? null,
  runtimeStatus: null,
  streamState: "idle",
  lastStreamError: null,
  transport: "http_json",
  inputModes: ["text/plain"],
  outputModes: ["text/plain"],
  metadata: session.metadata ?? {},
  externalSessionRef: session.externalSessionRef ?? null,
  lastActiveAt: getSessionLastActiveAt(session),
});

export const buildPersistedSessions = (
  sessions: Record<string, AgentSession>,
  maxPersisted = CHAT_SESSION_MAX_PERSISTED,
) => {
  if (maxPersisted <= 0) {
    return {};
  }

  const sorted = sortSessionsByLastActive(Object.entries(sessions)).slice(
    0,
    maxPersisted,
  );

  return sorted.reduce<Record<string, AgentSession>>(
    (acc, [conversationId, session]) => {
      acc[conversationId] = normalizeSessionForPersistence(session);
      return acc;
    },
    {},
  );
};

export const buildSessionCleanupPlan = (
  sessions: Record<string, AgentSession>,
  messageConversationIds: string[],
  now: Date = new Date(),
  maxActiveSessions = CHAT_SESSION_MAX_ACTIVE,
) => {
  const deadline = new Date(now.getTime() - CHAT_SESSION_TTL_MS).toISOString();
  const nextSessions = { ...sessions };
  const expiredConversationIds: string[] = [];
  const trimmedConversationIds: string[] = [];

  Object.entries(sessions).forEach(([conversationId, session]) => {
    if (session.lastActiveAt < deadline) {
      delete nextSessions[conversationId];
      expiredConversationIds.push(conversationId);
    }
  });

  const activeEntries = sortSessionsByLastActive(Object.entries(nextSessions));
  if (maxActiveSessions > 0 && activeEntries.length > maxActiveSessions) {
    activeEntries.slice(maxActiveSessions).forEach(([conversationId]) => {
      delete nextSessions[conversationId];
      trimmedConversationIds.push(conversationId);
    });
  }

  const orphanedMessageConversationIds = messageConversationIds.filter(
    (conversationId) => !nextSessions[conversationId],
  );
  const changed =
    expiredConversationIds.length > 0 ||
    trimmedConversationIds.length > 0 ||
    orphanedMessageConversationIds.length > 0;

  return {
    sessions: nextSessions,
    expiredConversationIds,
    trimmedConversationIds,
    orphanedMessageConversationIds,
    changed,
  };
};
