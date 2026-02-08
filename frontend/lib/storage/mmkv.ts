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
      id: "a2a-universal-client-storage",
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
        window.localStorage.setItem(name, value);
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
