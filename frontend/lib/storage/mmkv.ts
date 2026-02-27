import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { MMKV } from "react-native-mmkv";
import { type StateStorage, createJSONStorage } from "zustand/middleware";

const isExpoGo = Constants?.appOwnership === "expo";
const isWeb = Platform.OS === "web";

const MMKV_ENCRYPTION_KEY = "a2a-mmkv-encryption-key";
const CHAT_PERSIST_KEY = "a2a-client-hub.chat";
const LEGACY_STORAGE_KEYS = [
  "a2a-client-hub.messages",
  "a2a-client-hub.shortcuts",
];
const CHAT_QUOTA_FALLBACK_LIMITS = [40, 20, 10, 5, 1] as const;
const MMKV_INSTANCE_ID_DEFAULT = "a2a-client-hub-storage";
const MMKV_INSTANCE_ID_CHAT = "a2a-chat-storage";
const MMKV_INSTANCE_ID_MESSAGES = "a2a-messages-storage";

const mmkvInstances: Record<string, MMKV> = {};

const bytesToHex = (bytes: Uint8Array) =>
  Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

const generateEncryptionKey = async () => {
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    const array = new Uint8Array(32);
    crypto.getRandomValues(array);
    return bytesToHex(array);
  }

  const bytes = await Crypto.getRandomBytesAsync(32);
  return bytesToHex(bytes);
};

const getBackupKey = (name: string) => `${name}.bak`;

const shouldRunConsistencyCheck = (name: string) =>
  name.startsWith("a2a-client-hub.");

const isValidPersistedPayload = (name: string, value: string): boolean => {
  if (!shouldRunConsistencyCheck(name)) {
    return true;
  }
  try {
    JSON.parse(value);
    return true;
  } catch {
    return false;
  }
};

const shouldBackupKey = (name: string): boolean => {
  if (name === CHAT_PERSIST_KEY) {
    return false;
  }
  return !name.includes("messages");
};

const getInstanceId = (name: string) => {
  if (name.includes("messages")) {
    return MMKV_INSTANCE_ID_MESSAGES;
  }
  if (name === CHAT_PERSIST_KEY || name.includes("chat")) {
    return MMKV_INSTANCE_ID_CHAT;
  }
  return MMKV_INSTANCE_ID_DEFAULT;
};

const getMmkvInstance = async (
  instanceId: string = MMKV_INSTANCE_ID_DEFAULT,
) => {
  if (isWeb || isExpoGo) return null;
  if (mmkvInstances[instanceId]) return mmkvInstances[instanceId];

  try {
    let encryptionKey = await SecureStore.getItemAsync(MMKV_ENCRYPTION_KEY);
    if (!encryptionKey) {
      encryptionKey = await generateEncryptionKey();
      await SecureStore.setItemAsync(MMKV_ENCRYPTION_KEY, encryptionKey);
    }
    mmkvInstances[instanceId] = new MMKV({
      id: instanceId,
      encryptionKey,
    });
    return mmkvInstances[instanceId];
  } catch (error) {
    console.error(
      `[storage] Failed to initialize encrypted MMKV (${instanceId}):`,
      error,
    );
    return null;
  }
};

const asyncStorageFallback: StateStorage = {
  getItem: async (name) => {
    return await AsyncStorage.getItem(name);
  },
  setItem: async (name, value) => {
    await AsyncStorage.setItem(name, value);
  },
  removeItem: async (name) => {
    await AsyncStorage.removeItem(name);
  },
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

const compactChatPersistPayload = (
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

const setWebStorageWithQuotaRecovery = (
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

export const mmkvStateStorage: StateStorage = {
  getItem: async (name) => {
    if (isWeb) {
      return typeof window !== "undefined" && window.localStorage
        ? window.localStorage.getItem(name)
        : null;
    }
    const mmkv = await getMmkvInstance(getInstanceId(name));
    if (mmkv) {
      try {
        const value = mmkv.getString(name);
        if (typeof value !== "string") {
          return null;
        }
        if (!isValidPersistedPayload(name, value)) {
          throw new Error("Invalid JSON payload");
        }
        return value;
      } catch (error) {
        const backupKey = getBackupKey(name);
        console.error(
          `[storage] Corrupted persisted payload detected for ${name}.`,
          error,
        );
        try {
          const backup = mmkv.getString(backupKey);
          if (
            typeof backup === "string" &&
            isValidPersistedPayload(name, backup)
          ) {
            try {
              mmkv.set(name, backup);
            } catch (restoreError) {
              console.warn(
                `[storage] Failed to restore ${name} from backup to primary key.`,
                restoreError,
              );
            }
            console.warn("[storage] Recovered persisted payload from backup.", {
              key: name,
            });
            return backup;
          }
        } catch (backupError) {
          console.error(
            `[storage] Failed to read backup for ${name}.`,
            backupError,
          );
        }

        try {
          mmkv.delete(name);
          mmkv.delete(backupKey);
        } catch (cleanupError) {
          console.warn(
            `[storage] Failed to cleanup corrupted payload for ${name}.`,
            cleanupError,
          );
        }
        console.warn("[storage] Dropped corrupted persisted payload.", {
          key: name,
        });
        return null;
      }
    }
    return await asyncStorageFallback.getItem(name);
  },
  setItem: async (name, value) => {
    if (isWeb) {
      if (typeof window !== "undefined" && window.localStorage) {
        setWebStorageWithQuotaRecovery(window.localStorage, name, value);
      }
      return;
    }
    const mmkv = await getMmkvInstance(getInstanceId(name));
    if (mmkv) {
      try {
        mmkv.set(name, value);
        if (shouldBackupKey(name)) {
          mmkv.set(getBackupKey(name), value);
        }
        return;
      } catch (error) {
        console.error(
          `[storage] Failed to write ${name} to MMKV, falling back to AsyncStorage.`,
          error,
        );
      }
    }
    try {
      await asyncStorageFallback.setItem(name, value);
    } catch (fallbackError) {
      console.error(
        `[storage] AsyncStorage fallback write failed for ${name}.`,
        fallbackError,
      );
    }
  },
  removeItem: async (name) => {
    if (isWeb) {
      if (typeof window !== "undefined" && window.localStorage) {
        window.localStorage.removeItem(name);
      }
      return;
    }
    const mmkv = await getMmkvInstance(getInstanceId(name));
    if (mmkv) {
      try {
        mmkv.delete(name);
        mmkv.delete(getBackupKey(name));
        return;
      } catch (error) {
        console.error(
          `[storage] Failed to delete ${name} from MMKV, falling back to AsyncStorage.`,
          error,
        );
      }
    }
    try {
      await asyncStorageFallback.removeItem(name);
    } catch (fallbackError) {
      console.error(
        `[storage] AsyncStorage fallback delete failed for ${name}.`,
        fallbackError,
      );
    }
  },
};

export const createPersistStorage = () =>
  createJSONStorage(() => mmkvStateStorage);
