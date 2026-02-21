import "@testing-library/react-native/extend-expect";

const ensureBase64 = () => {
  if (typeof globalThis.btoa !== "function") {
    globalThis.btoa = (value: string) =>
      Buffer.from(value, "utf-8").toString("base64");
  }
  if (typeof globalThis.atob !== "function") {
    globalThis.atob = (value: string) =>
      Buffer.from(value, "base64").toString("utf-8");
  }
};

ensureBase64();

jest.mock("expo-constants", () => ({
  appOwnership: "standalone",
  expoConfig: {},
  manifest: {},
}));

jest.mock("react-native-mmkv", () => {
  class MockMMKV {
    private store = new Map<string, string>();

    getString(key: string) {
      return this.store.get(key) ?? null;
    }

    set(key: string, value: string) {
      this.store.set(key, value);
    }

    delete(key: string) {
      this.store.delete(key);
    }
  }
  return { MMKV: MockMMKV };
});

jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

jest.mock("expo-clipboard", () => ({
  setStringAsync: jest.fn(async () => {}),
  getStringAsync: jest.fn(async () => null),
}));
