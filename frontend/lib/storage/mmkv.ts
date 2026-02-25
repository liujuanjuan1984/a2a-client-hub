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
        window.localStorage.setItem(name, value);
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
