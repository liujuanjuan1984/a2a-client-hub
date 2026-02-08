import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { type StateStorage, createJSONStorage } from "zustand/middleware";

const isWeb = Platform.OS === "web";

export const secureStateStorage: StateStorage = (() => {
  if (isWeb) {
    if (typeof window !== "undefined" && window.sessionStorage) {
      return {
        getItem: (name) => window.sessionStorage.getItem(name),
        setItem: (name, value) => window.sessionStorage.setItem(name, value),
        removeItem: (name) => window.sessionStorage.removeItem(name),
      } satisfies StateStorage;
    }
  }

  return {
    getItem: async (name) => {
      return await SecureStore.getItemAsync(name);
    },
    setItem: async (name, value) => {
      await SecureStore.setItemAsync(name, value);
    },
    removeItem: async (name) => {
      await SecureStore.deleteItemAsync(name);
    },
  };
})();

export const createSecurePersistStorage = () =>
  createJSONStorage(() => secureStateStorage);
