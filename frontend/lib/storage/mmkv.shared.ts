export const WEB_TAB_ID_KEY = "a2a-client-hub.tab-id";
export const CHAT_PERSIST_KEY = "a2a-client-hub.chat";
export const AGENTS_PERSIST_KEY = "a2a-client-hub.agents";
export const LEGACY_STORAGE_KEYS = [
  "a2a-client-hub.messages",
  "a2a-client-hub.shortcuts",
];
export const CHAT_QUOTA_FALLBACK_LIMITS = [40, 20, 10, 5, 1] as const;
export const MMKV_ENCRYPTION_KEY = "a2a-mmkv-encryption-key";
export const MMKV_INSTANCE_ID_DEFAULT = "a2a-client-hub-storage";
export const MMKV_INSTANCE_ID_CHAT = "a2a-chat-storage";
export const MMKV_INSTANCE_ID_MESSAGES = "a2a-messages-storage";

export type PersistScope = "shared" | "web_tab";

export const bytesToHex = (bytes: Uint8Array) =>
  Array.from(bytes)
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");

const shouldRunConsistencyCheck = (name: string) =>
  name.startsWith("a2a-client-hub.");

const resolvePersistKeyFamily = (name: string) => {
  if (name === CHAT_PERSIST_KEY || name.startsWith(`${CHAT_PERSIST_KEY}.`)) {
    return CHAT_PERSIST_KEY;
  }
  if (
    name === AGENTS_PERSIST_KEY ||
    name.startsWith(`${AGENTS_PERSIST_KEY}.`)
  ) {
    return AGENTS_PERSIST_KEY;
  }
  return name;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

const isPersistEnvelopeShape = (value: unknown): boolean => {
  if (!isRecord(value)) {
    return false;
  }
  if ("version" in value && typeof value.version !== "number") {
    return false;
  }
  if ("state" in value && !isRecord(value.state)) {
    return false;
  }
  return true;
};

const persistedPayloadValidators: Record<string, (value: unknown) => boolean> =
  {
    [CHAT_PERSIST_KEY]: (value) => {
      if (!isPersistEnvelopeShape(value)) {
        return false;
      }
      if (!("state" in (value as Record<string, unknown>))) {
        return false;
      }
      const state = (value as { state?: unknown }).state;
      if (!isRecord(state)) {
        return false;
      }
      if (!("sessions" in state)) {
        return false;
      }
      return isRecord(state.sessions);
    },
    [AGENTS_PERSIST_KEY]: (value) => {
      if (!isPersistEnvelopeShape(value)) {
        return false;
      }
      if (!("state" in (value as Record<string, unknown>))) {
        return false;
      }
      const state = (value as { state?: unknown }).state;
      if (!isRecord(state)) {
        return false;
      }
      if (!("activeAgentId" in state)) {
        return false;
      }
      return (
        typeof state.activeAgentId === "string" || state.activeAgentId === null
      );
    },
  };

export const isValidPersistedPayload = (
  name: string,
  value: string,
): boolean => {
  if (!shouldRunConsistencyCheck(name)) {
    return true;
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    const validator = persistedPayloadValidators[resolvePersistKeyFamily(name)];
    if (!validator) {
      return true;
    }
    return validator(parsed);
  } catch {
    return false;
  }
};

const toRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const sortSessionsByLastActive = (
  sessions: Record<string, unknown>,
): [string, unknown][] => {
  return Object.entries(sessions).sort((left, right) => {
    const leftSession = toRecord(left[1]);
    const rightSession = toRecord(right[1]);
    const leftLastActiveAt =
      typeof leftSession?.lastActiveAt === "string"
        ? leftSession.lastActiveAt
        : "";
    const rightLastActiveAt =
      typeof rightSession?.lastActiveAt === "string"
        ? rightSession.lastActiveAt
        : "";
    return rightLastActiveAt.localeCompare(leftLastActiveAt);
  });
};

export const compactChatPersistPayload = (
  rawPayload: string,
  maxSessions: number,
): string | null => {
  if (maxSessions < 1) {
    return null;
  }
  try {
    const parsed = JSON.parse(rawPayload) as {
      state?: { sessions?: unknown };
      version?: unknown;
    };
    const sessions = toRecord(parsed.state?.sessions);
    if (!sessions) {
      return null;
    }
    const compactedSessions = sortSessionsByLastActive(sessions)
      .slice(0, maxSessions)
      .reduce<Record<string, unknown>>((acc, [conversationId, session]) => {
        acc[conversationId] = session;
        return acc;
      }, {});
    return JSON.stringify({
      ...parsed,
      state: {
        ...(parsed.state ?? {}),
        sessions: compactedSessions,
      },
    });
  } catch {
    return null;
  }
};

const isQuotaExceededError = (error: unknown): boolean => {
  if (!(error instanceof Error)) {
    return false;
  }
  const namedError = error as Error & { code?: unknown };
  const name = (namedError.name ?? "").toLowerCase();
  const message = (namedError.message ?? "").toLowerCase();
  return (
    name.includes("quotaexceeded") ||
    name.includes("ns_error_dom_quota_reached") ||
    namedError.code === 22 ||
    message.includes("quota")
  );
};

const generateWebTabId = () => {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    return bytesToHex(bytes);
  }
  return `tab-${Math.random().toString(16).slice(2)}`;
};

const getOrCreateWebTabId = () => {
  if (
    typeof window === "undefined" ||
    typeof window.sessionStorage === "undefined"
  ) {
    return null;
  }
  const existing = window.sessionStorage.getItem(WEB_TAB_ID_KEY)?.trim();
  if (existing) {
    return existing;
  }
  const generated = generateWebTabId();
  if (!generated) {
    return null;
  }
  window.sessionStorage.setItem(WEB_TAB_ID_KEY, generated);
  return generated;
};

export const buildWebPersistStorageName = (
  baseKey: string,
  scope: PersistScope = "shared",
) => {
  if (scope !== "web_tab") {
    return baseKey;
  }
  const tabId = getOrCreateWebTabId();
  return tabId ? `${baseKey}.${tabId}` : baseKey;
};

export const setWebStorageWithQuotaRecovery = (
  storage: Storage,
  name: string,
  value: string,
) => {
  try {
    storage.setItem(name, value);
    return;
  } catch (error) {
    if (!isQuotaExceededError(error)) {
      throw error;
    }
  }

  LEGACY_STORAGE_KEYS.forEach((legacyKey) => {
    try {
      storage.removeItem(legacyKey);
    } catch {
      // Ignore cleanup failures and continue best-effort recovery.
    }
  });

  try {
    storage.setItem(name, value);
    return;
  } catch (error) {
    if (!isQuotaExceededError(error)) {
      throw error;
    }
  }

  if (name === CHAT_PERSIST_KEY) {
    for (const maxSessions of CHAT_QUOTA_FALLBACK_LIMITS) {
      const compactedPayload = compactChatPersistPayload(value, maxSessions);
      if (!compactedPayload) {
        break;
      }
      try {
        storage.setItem(name, compactedPayload);
        console.warn(
          "[storage] LocalStorage quota reached, compacted persisted chat sessions.",
          { maxSessions },
        );
        return;
      } catch (error) {
        if (!isQuotaExceededError(error)) {
          throw error;
        }
      }
    }
  }

  try {
    storage.removeItem(name);
  } catch {
    // Ignore and keep no-op fallback.
  }
  console.warn(
    "[storage] LocalStorage quota reached, skipped persistence for key.",
    { key: name },
  );
};

export const getInstanceId = (name: string) => {
  if (name.includes("messages")) {
    return MMKV_INSTANCE_ID_MESSAGES;
  }
  if (name === CHAT_PERSIST_KEY || name.startsWith(`${CHAT_PERSIST_KEY}.`)) {
    return MMKV_INSTANCE_ID_CHAT;
  }
  return MMKV_INSTANCE_ID_DEFAULT;
};
