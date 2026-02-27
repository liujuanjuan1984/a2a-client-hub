import "@testing-library/react-native/extend-expect";
import { queryClient } from "@/services/queryClient";

jest.mock("react-native-reanimated", () => {
  const Reanimated = require("react-native-reanimated/mock");
  Reanimated.default.call = () => {};
  return Reanimated;
});

if (typeof globalThis.window === "undefined") {
  globalThis.window = globalThis as unknown as Window & typeof globalThis;
}

if (typeof (globalThis.window as Window).addEventListener !== "function") {
  (globalThis.window as Window).addEventListener = () => {};
}

if (typeof (globalThis.window as Window).removeEventListener !== "function") {
  (globalThis.window as Window).removeEventListener = () => {};
}

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

jest.mock("@expo/vector-icons", () => {
  const MockIcon = () => null;
  return {
    Ionicons: MockIcon,
    AntDesign: MockIcon,
    FontAwesome: MockIcon,
    FontAwesome5: MockIcon,
    MaterialIcons: MockIcon,
    MaterialCommunityIcons: MockIcon,
  };
});

jest.mock("react-native/Libraries/AppState/AppState", () => ({
  AppState: {
    addEventListener: jest.fn(() => ({ remove: jest.fn() })),
    currentState: "active",
  },
}));

jest.mock("react-native/Libraries/Utilities/Dimensions", () => {
  const dimensions = {
    window: { width: 375, height: 812, scale: 2, fontScale: 2 },
    screen: { width: 375, height: 812, scale: 2, fontScale: 2 },
  };
  const dimensionsModule = {
    get: (key: "window" | "screen") => dimensions[key],
    set: jest.fn(),
    addEventListener: () => ({
      remove: jest.fn(),
    }),
    removeEventListener: jest.fn(),
  };

  return {
    __esModule: true,
    default: dimensionsModule,
    ...dimensionsModule,
  };
});

afterEach(async () => {
  await queryClient.cancelQueries();
  queryClient.clear();
});
