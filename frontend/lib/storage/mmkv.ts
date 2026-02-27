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

const getMmkvInstance = async (id: string = "a2a-client-hub-storage") => {
  if (isWeb || isExpoGo) return null;
  if (mmkvInstances[id]) return mmkvInstances[id];

  try {
    let encryptionKey = await SecureStore.getItemAsync(MMKV_ENCRYPTION_KEY);
    if (!encryptionKey) {
      encryptionKey = await generateEncryptionKey();
      await SecureStore.setItemAsync(MMKV_ENCRYPTION_KEY, encryptionKey);
    }
    mmkvInstances[id] = new MMKV({
      id,
      encryptionKey,
    });
    return mmkvInstances[id];
  } catch (error) {
    console.error(
      `[storage] Failed to initialize encrypted MMKV (${id}):`,
      error,
    );
    return null;
  }
};

const getInstanceId = (name: string) => {
  if (name.includes("messages")) return "a2a-messages-storage";
  if (name.includes("chat") || name.includes("session"))
    return "a2a-session-storage";
  return "a2a-client-hub-storage";
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
        if (value) {
          // Basic consistency check: must be valid JSON if it's not empty
          JSON.parse(value);
          return value;
        }
        return null;
      } catch (error) {
        console.error(`[storage] Data corruption detected for ${name}:`, error);
        // Try recovery from backup if available
        try {
          const backup = mmkv.getString(`${name}.bak`);
          if (backup) {
            JSON.parse(backup);
            console.info(`[storage] Recovered ${name} from backup`);
            return backup;
          }
        } catch (backupError) {
          console.error(
            `[storage] Backup also corrupted for ${name}:`,
            backupError,
          );
        }
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
        // Save backup for critical stores (non-messages)
        if (!name.includes("messages")) {
          mmkv.set(`${name}.bak`, value);
        }
      } catch (error) {
        console.error(`[storage] Failed to set ${name} in MMKV:`, error);
      }
      return;
    }
    await asyncStorageFallback.setItem(name, value);
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
        mmkv.delete(`${name}.bak`);
      } catch (error) {
        console.error(`[storage] Failed to delete ${name} from MMKV:`, error);
      }
      return;
    }
    await asyncStorageFallback.removeItem(name);
  },
};

export const createPersistStorage = () =>
  createJSONStorage(() => mmkvStateStorage);
