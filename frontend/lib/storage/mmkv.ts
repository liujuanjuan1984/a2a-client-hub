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

let mmkvInstance: MMKV | null = null;

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

const getMmkvInstance = async () => {
  if (isWeb || isExpoGo) return null;
  if (mmkvInstance) return mmkvInstance;

  try {
    let encryptionKey = await SecureStore.getItemAsync(MMKV_ENCRYPTION_KEY);
    if (!encryptionKey) {
      encryptionKey = await generateEncryptionKey();
      await SecureStore.setItemAsync(MMKV_ENCRYPTION_KEY, encryptionKey);
    }
    mmkvInstance = new MMKV({
      id: "a2a-client-hub-storage",
      encryptionKey,
    });
    return mmkvInstance;
  } catch (error) {
    console.error("[storage] Failed to initialize encrypted MMKV:", error);
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
    const mmkv = await getMmkvInstance();
    if (mmkv) {
      return mmkv.getString(name) ?? null;
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
    const mmkv = await getMmkvInstance();
    if (mmkv) {
      mmkv.set(name, value);
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
    const mmkv = await getMmkvInstance();
    if (mmkv) {
      mmkv.delete(name);
      return;
    }
    await asyncStorageFallback.removeItem(name);
  },
};

export const createPersistStorage = () =>
  createJSONStorage(() => mmkvStateStorage);
