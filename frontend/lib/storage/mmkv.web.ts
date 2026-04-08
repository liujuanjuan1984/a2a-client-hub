import { type StateStorage, createJSONStorage } from "zustand/middleware";

import {
  buildWebPersistStorageName,
  isValidPersistedPayload,
  setWebStorageWithQuotaRecovery,
  type PersistScope,
} from "./mmkv.shared";

export const buildPersistStorageName = (
  baseKey: string,
  scope: PersistScope = "shared",
) => buildWebPersistStorageName(baseKey, scope);

export const mmkvStateStorage: StateStorage = {
  getItem: async (name) => {
    return typeof window !== "undefined" && window.localStorage
      ? window.localStorage.getItem(name)
      : null;
  },
  setItem: async (name, value) => {
    if (typeof window !== "undefined" && window.localStorage) {
      setWebStorageWithQuotaRecovery(window.localStorage, name, value);
    }
  },
  removeItem: async (name) => {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.removeItem(name);
    }
  },
};

export const createPersistStorage = () =>
  createJSONStorage(() => mmkvStateStorage);

export { isValidPersistedPayload };
