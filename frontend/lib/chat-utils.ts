import type { A2AAgentInvokeRequest } from "@/lib/api/a2aAgents";
import type {
  PendingRuntimeInterrupt,
  ResolvedRuntimeInterrupt,
} from "@/lib/api/chat-utils";
import { getInvokeMetadataBindings } from "@/lib/invokeMetadata";
import { pickOpencodeDirectoryMetadata } from "@/lib/opencodeMetadata";
import {
  pickSharedMetadataSections,
  withoutSharedSessionBinding,
} from "@/lib/sharedMetadata";

type ExternalSessionRef = {
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
  runtimeStatus?: string | null;
  pendingInterrupts: PendingRuntimeInterrupt[];
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
const CHAT_SESSION_TTL_MS = 14 * 24 * 60 * 60 * 1000;
const CHAT_SESSION_MAX_ACTIVE = 240;
const CHAT_SESSION_MAX_PERSISTED = 80;

export const createAgentSession = (agentId: string): AgentSession => ({
  agentId,
  createdAt: new Date().toISOString(),
  source: null,
  runtimeStatus: null,
  pendingInterrupts: [],
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

const isPendingRuntimeInterrupt = (
  value: unknown,
): value is PendingRuntimeInterrupt => {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as PendingRuntimeInterrupt;
  return (
    typeof candidate.requestId === "string" &&
    (candidate.type === "permission" ||
      candidate.type === "question" ||
      candidate.type === "permissions" ||
      candidate.type === "elicitation") &&
    candidate.phase === "asked"
  );
};

export const getPendingInterruptQueue = (
  session:
    | Pick<AgentSession, "pendingInterrupts" | "pendingInterrupt">
    | null
    | undefined,
): PendingRuntimeInterrupt[] => {
  const pendingInterrupts = Array.isArray(session?.pendingInterrupts)
    ? session.pendingInterrupts.filter(isPendingRuntimeInterrupt)
    : [];
  if (pendingInterrupts.length > 0) {
    return pendingInterrupts;
  }
  return isPendingRuntimeInterrupt(session?.pendingInterrupt)
    ? [session.pendingInterrupt]
    : [];
};

export const getPendingInterrupt = (
  session:
    | Pick<AgentSession, "pendingInterrupts" | "pendingInterrupt">
    | null
    | undefined,
): PendingRuntimeInterrupt | null =>
  getPendingInterruptQueue(session)[0] ?? null;

export const hasPendingInterrupt = (
  session:
    | Pick<AgentSession, "pendingInterrupts" | "pendingInterrupt">
    | null
    | undefined,
) => getPendingInterruptQueue(session).length > 0;

export const buildPendingInterruptState = (
  pendingInterrupts: PendingRuntimeInterrupt[],
): Pick<AgentSession, "pendingInterrupts" | "pendingInterrupt"> => ({
  pendingInterrupts,
  pendingInterrupt: pendingInterrupts[0] ?? null,
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
  const metadata = withoutSharedSessionBinding(session.metadata);
  const externalProvider = session.externalSessionRef?.provider?.trim();
  const externalSessionId =
    session.externalSessionRef?.externalSessionId?.trim();
  const providerForSessionBinding = externalProvider?.trim().toLowerCase();
  if (externalSessionId || providerForSessionBinding) {
    payload.sessionBinding = {
      provider: providerForSessionBinding || null,
      externalSessionId: externalSessionId || null,
    };
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
): AgentSession => {
  const sharedMetadata = pickSharedMetadataSections(session.metadata, [
    "model",
  ]);
  const invokeBindings = getInvokeMetadataBindings(session.metadata);
  const persistedMetadata = {
    ...sharedMetadata,
    ...(Object.keys(invokeBindings).length > 0
      ? {
          shared: {
            ...(sharedMetadata.shared as Record<string, unknown> | undefined),
            invoke: {
              bindings: invokeBindings,
            },
          },
        }
      : {}),
    ...(pickOpencodeDirectoryMetadata(session.metadata) ?? {}),
  };

  return {
    agentId: session.agentId,
    createdAt: getSessionCreatedAt(session),
    source: null,
    runtimeStatus: null,
    pendingInterrupts: [],
    pendingInterrupt: null,
    lastResolvedInterrupt: null,
    streamState: "idle",
    lastStreamError: null,
    transport: "http_json",
    inputModes: ["text/plain"],
    outputModes: ["text/plain"],
    metadata: persistedMetadata,
    externalSessionRef: null,
    lastActiveAt: getSessionLastActiveAt(session),
  };
};

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
