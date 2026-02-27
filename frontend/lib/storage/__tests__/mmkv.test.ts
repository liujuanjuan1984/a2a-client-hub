const makeQuotaError = () => {
  const error = new Error("exceeded quota");
  (error as Error & { name: string }).name = "QuotaExceededError";
  return error;
};

type NativeModuleOptions = {
  failSetKeys?: string[];
  failGetKeys?: string[];
  failDeleteKeys?: string[];
};

const loadWebStorageModule = (storage: {
  getItem: jest.Mock;
  setItem: jest.Mock;
  removeItem: jest.Mock;
}) => {
  jest.resetModules();
  (globalThis as { window?: unknown }).window = { localStorage: storage };

  jest.doMock("react-native", () => ({
    Platform: { OS: "web" },
  }));
  jest.doMock("expo-constants", () => ({
    __esModule: true,
    default: { appOwnership: null },
  }));
  jest.doMock("expo-crypto", () => ({
    getRandomBytesAsync: jest.fn(),
  }));
  jest.doMock("expo-secure-store", () => ({
    getItemAsync: jest.fn(),
    setItemAsync: jest.fn(),
  }));
  jest.doMock("react-native-mmkv", () => ({
    MMKV: jest.fn(),
  }));

  return require("../mmkv") as typeof import("../mmkv");
};

const loadNativeStorageModule = (options: NativeModuleOptions = {}) => {
  jest.resetModules();
  delete (globalThis as { window?: unknown }).window;

  const stores = new Map<string, Map<string, string>>();
  const asyncStore = new Map<string, string>();
  const failSetKeys = new Set(options.failSetKeys ?? []);
  const failGetKeys = new Set(options.failGetKeys ?? []);
  const failDeleteKeys = new Set(options.failDeleteKeys ?? []);
  const asyncStorage = {
    getItem: jest.fn(async (key: string) => asyncStore.get(key) ?? null),
    setItem: jest.fn(async (key: string, value: string) => {
      asyncStore.set(key, value);
    }),
    removeItem: jest.fn(async (key: string) => {
      asyncStore.delete(key);
    }),
  };

  jest.doMock("react-native", () => ({
    Platform: { OS: "ios" },
  }));
  jest.doMock("expo-constants", () => ({
    __esModule: true,
    default: { appOwnership: null },
  }));
  jest.doMock("expo-crypto", () => ({
    getRandomBytesAsync: jest.fn(async () => new Uint8Array(32)),
  }));
  jest.doMock("expo-secure-store", () => ({
    getItemAsync: jest.fn(async () => null),
    setItemAsync: jest.fn(async () => undefined),
  }));
  jest.doMock("@react-native-async-storage/async-storage", () => ({
    __esModule: true,
    default: asyncStorage,
    ...asyncStorage,
  }));
  jest.doMock("react-native-mmkv", () => ({
    MMKV: class MockMMKV {
      private readonly id: string;

      constructor(config: { id: string }) {
        this.id = config.id;
        if (!stores.has(this.id)) {
          stores.set(this.id, new Map<string, string>());
        }
      }

      getString(key: string) {
        if (failGetKeys.has(`${this.id}:${key}`)) {
          throw new Error("mock get failure");
        }
        return stores.get(this.id)?.get(key) ?? null;
      }

      set(key: string, value: string) {
        if (failSetKeys.has(`${this.id}:${key}`)) {
          throw new Error("mock set failure");
        }
        stores.get(this.id)?.set(key, value);
      }

      delete(key: string) {
        if (failDeleteKeys.has(`${this.id}:${key}`)) {
          throw new Error("mock delete failure");
        }
        stores.get(this.id)?.delete(key);
      }
    },
  }));

  const mmkv = require("../mmkv") as typeof import("../mmkv");
  return {
    ...mmkv,
    stores,
    asyncStorage,
    asyncStore,
  };
};

describe("mmkvStateStorage web quota recovery", () => {
  afterEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
    delete (globalThis as { window?: unknown }).window;
  });

  it("reclaims legacy keys and retries when quota is exceeded", async () => {
    let callCount = 0;
    const storage = {
      getItem: jest.fn(),
      setItem: jest.fn(() => {
        callCount += 1;
        if (callCount === 1) {
          throw makeQuotaError();
        }
      }),
      removeItem: jest.fn(),
    };
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});

    const { mmkvStateStorage } = loadWebStorageModule(storage);
    await expect(
      mmkvStateStorage.setItem("a2a-client-hub.chat", "payload"),
    ).resolves.toBeUndefined();

    expect(storage.setItem).toHaveBeenCalledTimes(2);
    expect(storage.removeItem).toHaveBeenCalledWith("a2a-client-hub.messages");
    expect(storage.removeItem).toHaveBeenCalledWith("a2a-client-hub.shortcuts");
    expect(warnSpy).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("compacts persisted chat payload when quota remains exceeded", async () => {
    const sessions = Object.fromEntries(
      Array.from({ length: 80 }, (_, index) => {
        const id = `conv-${String(index).padStart(3, "0")}`;
        return [
          id,
          {
            agentId: "agent-1",
            createdAt: "2026-01-01T00:00:00.000Z",
            source: null,
            contextId: null,
            runtimeStatus: null,
            pendingInterrupt: null,
            streamState: "idle",
            lastStreamError: null,
            transport: "http_json",
            inputModes: ["text/plain"],
            outputModes: ["text/plain"],
            metadata: {},
            externalSessionRef: null,
            lastActiveAt: `2026-01-${String((index % 28) + 1).padStart(2, "0")}T00:00:00.000Z`,
          },
        ];
      }),
    );
    const rawPayload = JSON.stringify({ state: { sessions }, version: 0 });

    const storage = {
      getItem: jest.fn(),
      setItem: jest.fn((_name: string, value: string) => {
        if (value.includes("conv-079")) {
          throw makeQuotaError();
        }
      }),
      removeItem: jest.fn(),
    };
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});

    const { mmkvStateStorage } = loadWebStorageModule(storage);
    await expect(
      mmkvStateStorage.setItem("a2a-client-hub.chat", rawPayload),
    ).resolves.toBeUndefined();

    const finalStoredPayload = storage.setItem.mock.calls.at(-1)?.[1];
    expect(typeof finalStoredPayload).toBe("string");
    const parsed = JSON.parse(finalStoredPayload as string) as {
      state: { sessions: Record<string, unknown> };
    };
    expect(Object.keys(parsed.state.sessions).length).toBeLessThan(80);
    expect(warnSpy).toHaveBeenCalledWith(
      "[storage] LocalStorage quota reached, compacted persisted chat sessions.",
      expect.objectContaining({ maxSessions: expect.any(Number) }),
    );
    warnSpy.mockRestore();
  });
});

describe("mmkvStateStorage native resilience", () => {
  afterEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
    delete (globalThis as { window?: unknown }).window;
  });

  it("separates key families into dedicated MMKV instances", async () => {
    const { mmkvStateStorage, stores } = loadNativeStorageModule();
    const chatPayload = JSON.stringify({ state: { sessions: {} } });
    const messagesPayload = JSON.stringify({ state: { byId: {} } });
    const agentsPayload = JSON.stringify({ state: { activeAgentId: null } });

    await mmkvStateStorage.setItem("a2a-client-hub.chat", chatPayload);
    await mmkvStateStorage.setItem("a2a-client-hub.messages", messagesPayload);
    await mmkvStateStorage.setItem("a2a-client-hub.agents", agentsPayload);

    expect(stores.get("a2a-chat-storage")?.get("a2a-client-hub.chat")).toBe(
      chatPayload,
    );
    expect(
      stores.get("a2a-messages-storage")?.get("a2a-client-hub.messages"),
    ).toBe(messagesPayload);
    expect(
      stores.get("a2a-client-hub-storage")?.get("a2a-client-hub.agents"),
    ).toBe(agentsPayload);
  });

  it("drops invalid MMKV payload and keeps fail-open behavior", async () => {
    const { mmkvStateStorage, stores } = loadNativeStorageModule();
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    const key = "a2a-client-hub.agents";
    const payload = JSON.stringify({ state: { activeAgentId: "agent-1" } });

    await mmkvStateStorage.setItem(key, payload);
    const defaultStore = stores.get("a2a-client-hub-storage");
    expect(defaultStore).toBeDefined();
    defaultStore?.set(key, JSON.stringify({ state: { activeAgentId: 123 } }));

    await expect(mmkvStateStorage.getItem(key)).resolves.toBeNull();
    expect(defaultStore?.has(key)).toBe(false);
    expect(warnSpy).toHaveBeenCalledWith(
      "[storage] Dropped invalid MMKV payload.",
      { key },
    );
    warnSpy.mockRestore();
  });

  it("does not read AsyncStorage when MMKV instance is available", async () => {
    const { mmkvStateStorage, asyncStore, asyncStorage } =
      loadNativeStorageModule();
    const key = "a2a-client-hub.agents";
    asyncStore.set(
      key,
      JSON.stringify({ state: { activeAgentId: "agent-1" } }),
    );

    await expect(mmkvStateStorage.getItem(key)).resolves.toBeNull();
    expect(asyncStorage.getItem).not.toHaveBeenCalled();
  });

  it("drops cache write when native set fails", async () => {
    const key = "a2a-client-hub.agents";
    const payload = JSON.stringify({ state: { activeAgentId: null } });
    const { mmkvStateStorage, asyncStorage, asyncStore } =
      loadNativeStorageModule({
        failSetKeys: [`a2a-client-hub-storage:${key}`],
      });
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});

    await expect(
      mmkvStateStorage.setItem(key, payload),
    ).resolves.toBeUndefined();
    expect(asyncStorage.setItem).not.toHaveBeenCalled();
    expect(asyncStore.has(key)).toBe(false);

    errorSpy.mockRestore();
  });

  it("keeps fail-open when native delete fails", async () => {
    const key = "a2a-client-hub.agents";
    const { mmkvStateStorage, asyncStorage } = loadNativeStorageModule({
      failDeleteKeys: [`a2a-client-hub-storage:${key}`],
    });
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});

    await expect(mmkvStateStorage.removeItem(key)).resolves.toBeUndefined();
    expect(asyncStorage.removeItem).not.toHaveBeenCalled();

    errorSpy.mockRestore();
  });
});
