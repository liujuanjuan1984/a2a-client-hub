import type { A2AAgentInvokeRequest } from "@/lib/api/a2aAgents";
import type {
  ChatMessage,
  MessageBlock,
  RuntimeInterrupt,
} from "@/lib/api/chat-utils";

export const isSameBlockList = (
  left: MessageBlock[] = [],
  right: MessageBlock[] = [],
) => {
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    const lhs = left[index];
    const rhs = right[index];
    if (!lhs || !rhs) return false;
    if (
      lhs.id !== rhs.id ||
      lhs.type !== rhs.type ||
      lhs.content !== rhs.content ||
      lhs.isFinished !== rhs.isFinished ||
      lhs.createdAt !== rhs.createdAt ||
      lhs.updatedAt !== rhs.updatedAt
    ) {
      return false;
    }
  }
  return true;
};

export const isSameMessageList = (
  left: ChatMessage[],
  right: ChatMessage[],
) => {
  if (left.length !== right.length) return false;
  return left.every((message, index) => {
    const next = right[index];
    if (!next) return false;
    return (
      message.id === next.id &&
      message.role === next.role &&
      message.content === next.content &&
      message.createdAt === next.createdAt &&
      isSameBlockList(message.blocks, next.blocks) &&
      message.status === next.status
    );
  });
};

export const COLLAPSED_TEXT_LINES = 10;
export const COLLAPSED_TEXT_CHAR_LIMIT = 300;

export const shouldCollapseByLength = (value: string) => {
  return value.length > COLLAPSED_TEXT_CHAR_LIMIT;
};

export type ExternalSessionRef = {
  provider?: string | null;
  externalSessionId?: string | null;
};

export type AgentSession = {
  agentId: string;
  source?: "manual" | "scheduled" | null;
  contextId: string | null;
  runtimeStatus?: string | null;
  pendingInterrupt?: RuntimeInterrupt | null;
  streamState?: "idle" | "streaming" | "recoverable" | "error";
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
  pendingInterrupt: null,
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
  provider: current?.provider ?? incoming.provider ?? null,
  externalSessionId:
    current?.externalSessionId ?? incoming.externalSessionId ?? null,
});

export const buildInvokePayload = (
  query: string,
  session: AgentSession,
  conversationId: string,
  options?: {
    userMessageId?: string;
    clientAgentMessageId?: string;
    resumeFromSequence?: number;
  },
): A2AAgentInvokeRequest => {
  const payload: A2AAgentInvokeRequest = { query, conversationId };
  if (options?.userMessageId) {
    payload.userMessageId = options.userMessageId;
  }
  if (options?.clientAgentMessageId) {
    payload.clientAgentMessageId = options.clientAgentMessageId;
  }
  if (options?.resumeFromSequence !== undefined) {
    payload.resumeFromSequence = options.resumeFromSequence;
  }
  if (session.contextId) {
    payload.contextId = session.contextId;
  }
  const metadata: Record<string, unknown> = { ...(session.metadata ?? {}) };
  const externalProvider = session.externalSessionRef?.provider?.trim();
  const externalSessionId =
    session.externalSessionRef?.externalSessionId?.trim();
  const metadataProvider =
    typeof metadata.provider === "string" ? metadata.provider.trim() : "";
  const providerForSessionBinding = (
    externalProvider ?? metadataProvider
  ).toLowerCase();
  if (externalProvider) {
    metadata.provider = externalProvider;
  }
  if (externalSessionId) {
    metadata.externalSessionId = externalSessionId;
    metadata.external_session_id = externalSessionId;
    if (providerForSessionBinding === "opencode") {
      metadata.opencode_session_id = externalSessionId;
    }
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
  pendingInterrupt: null,
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
