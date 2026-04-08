import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";
import { MMKV } from "react-native-mmkv";
import { type StateStorage, createJSONStorage } from "zustand/middleware";

import {
  MMKV_ENCRYPTION_KEY,
  bytesToHex,
  getInstanceId,
  isValidPersistedPayload,
  type PersistScope,
} from "./mmkv.shared";

const isExpoGo = Constants?.appOwnership === "expo";

const mmkvInstances: Record<string, MMKV> = {};

const generateEncryptionKey = async () => {
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    const array = new Uint8Array(32);
    crypto.getRandomValues(array);
    return bytesToHex(array);
  }

  const bytes = await Crypto.getRandomBytesAsync(32);
  return bytesToHex(bytes);
};

const getMmkvInstance = async (instanceId: string) => {
  if (isExpoGo) {
    return null;
  }
  if (mmkvInstances[instanceId]) {
    return mmkvInstances[instanceId];
  }

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

export const buildPersistStorageName = (
  baseKey: string,
  _scope: PersistScope = "shared",
) => baseKey;

export const mmkvStateStorage: StateStorage = {
  getItem: async (name) => {
    const mmkv = await getMmkvInstance(getInstanceId(name));
    if (mmkv) {
      try {
        const value = mmkv.getString(name);
        if (typeof value === "string") {
          if (!isValidPersistedPayload(name, value)) {
            try {
              mmkv.delete(name);
            } catch {}
            console.warn("[storage] Dropped invalid MMKV payload.", {
              key: name,
            });
            return null;
          }
          return value;
        }
        return null;
      } catch (error) {
        console.error(
          `[storage] Failed to read MMKV payload for ${name}.`,
          error,
        );
        return null;
      }
    }
    try {
      const fallbackValue = await asyncStorageFallback.getItem(name);
      if (typeof fallbackValue !== "string") {
        return null;
      }
      if (!isValidPersistedPayload(name, fallbackValue)) {
        await asyncStorageFallback.removeItem(name);
        console.warn("[storage] Dropped invalid AsyncStorage payload.", {
          key: name,
        });
        return null;
      }
      return fallbackValue;
    } catch (fallbackError) {
      console.error(
        `[storage] Failed to read AsyncStorage payload for ${name}.`,
        fallbackError,
      );
      return null;
    }
  },
  setItem: async (name, value) => {
    const mmkv = await getMmkvInstance(getInstanceId(name));
    if (mmkv) {
      try {
        mmkv.set(name, value);
        return;
      } catch (error) {
        console.error(
          `[storage] Failed to write MMKV payload for ${name}.`,
          error,
        );
        return;
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
    const mmkv = await getMmkvInstance(getInstanceId(name));
    if (mmkv) {
      try {
        mmkv.delete(name);
        return;
      } catch (error) {
        console.error(
          `[storage] Failed to delete MMKV payload for ${name}.`,
          error,
        );
        return;
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
