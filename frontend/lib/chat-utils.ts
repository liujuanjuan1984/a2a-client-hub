import type { A2AAgentInvokeRequest } from "@/lib/api/a2aAgents";
import type {
  ChatMessage,
  MessageBlock,
  PendingRuntimeInterrupt,
  ResolvedRuntimeInterrupt,
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

export type ExternalSessionRef = {
  provider?: string | null;
  externalSessionId?: string | null;
};

export type SharedModelSelection = {
  providerID: string;
  modelID: string;
};

export type ResolvedRuntimeInterruptRecord = ResolvedRuntimeInterrupt & {
  observedAt: string;
};

export type AgentSession = {
  agentId: string;
  createdAt?: string;
  source?: "manual" | "scheduled" | null;
  contextId: string | null;
  runtimeStatus?: string | null;
  pendingInterrupt?: PendingRuntimeInterrupt | null;
  lastResolvedInterrupt?: ResolvedRuntimeInterruptRecord | null;
  streamState?: "idle" | "streaming" | "recoverable" | "error";
  lastStreamError?: string | null;
  lastReceivedSequence?: number;
  lastUserMessageId?: string;
  lastAgentMessageId?: string;
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
  createdAt: new Date().toISOString(),
  source: null,
  contextId: null,
  runtimeStatus: null,
  pendingInterrupt: null,
  lastResolvedInterrupt: null,
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

const asRecord = (value: unknown): Record<string, unknown> | null =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

export const getSharedModelSelection = (
  metadata: Record<string, unknown> | null | undefined,
): SharedModelSelection | null => {
  const shared = asRecord(metadata?.shared);
  const model = asRecord(shared?.model);
  const providerID =
    typeof model?.providerID === "string" ? model.providerID.trim() : "";
  const modelID =
    typeof model?.modelID === "string" ? model.modelID.trim() : "";
  if (!providerID || !modelID) {
    return null;
  }
  return { providerID, modelID };
};

export const withSharedModelSelection = (
  metadata: Record<string, unknown> | null | undefined,
  selection: SharedModelSelection | null,
): Record<string, unknown> => {
  const nextMetadata = { ...(metadata ?? {}) };
  const nextShared = asRecord(nextMetadata.shared)
    ? { ...(nextMetadata.shared as Record<string, unknown>) }
    : {};

  if (selection) {
    nextShared.model = {
      providerID: selection.providerID,
      modelID: selection.modelID,
    };
    nextMetadata.shared = nextShared;
    return nextMetadata;
  }

  delete nextShared.model;
  if (Object.keys(nextShared).length > 0) {
    nextMetadata.shared = nextShared;
  } else {
    delete nextMetadata.shared;
  }
  return nextMetadata;
};

export const buildInvokePayload = (
  query: string,
  session: AgentSession,
  conversationId: string,
  options?: {
    userMessageId?: string;
    agentMessageId?: string;
    resumeFromSequence?: number;
    interrupt?: boolean;
  },
): A2AAgentInvokeRequest => {
  const payload: A2AAgentInvokeRequest = { query, conversationId };
  if (options?.userMessageId) {
    payload.userMessageId = options.userMessageId;
  }
  if (options?.agentMessageId) {
    payload.agentMessageId = options.agentMessageId;
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
  const providerForSessionBinding = (externalProvider ?? metadataProvider)
    .trim()
    .toLowerCase();
  if (providerForSessionBinding) {
    metadata.provider = providerForSessionBinding;
  }
  if (externalSessionId) {
    metadata.externalSessionId = externalSessionId;
  }
  if (Object.keys(metadata).length > 0) {
    payload.metadata = metadata;
  }
  if (options?.interrupt) {
    const resolvedMetadata: Record<string, unknown> = {
      ...((payload.metadata as Record<string, unknown> | undefined) ?? {}),
    };
    const currentExtensions =
      typeof resolvedMetadata.extensions === "object" &&
      resolvedMetadata.extensions !== null &&
      !Array.isArray(resolvedMetadata.extensions)
        ? { ...(resolvedMetadata.extensions as Record<string, unknown>) }
        : {};
    resolvedMetadata.extensions = {
      ...currentExtensions,
      interrupt: true,
    };
    payload.metadata = resolvedMetadata;
  }
  return payload;
};

const getSessionLastActiveAt = (session: AgentSession) =>
  typeof session.lastActiveAt === "string"
    ? session.lastActiveAt
    : FALLBACK_LAST_ACTIVE_AT;

const getSessionCreatedAt = (session: AgentSession) =>
  typeof session.createdAt === "string"
    ? session.createdAt
    : getSessionLastActiveAt(session);

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
  createdAt: getSessionCreatedAt(session),
  source: null,
  contextId: null,
  runtimeStatus: null,
  pendingInterrupt: null,
  lastResolvedInterrupt: null,
  streamState: "idle",
  lastStreamError: null,
  transport: "http_json",
  inputModes: ["text/plain"],
  outputModes: ["text/plain"],
  metadata: {},
  externalSessionRef: null,
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
