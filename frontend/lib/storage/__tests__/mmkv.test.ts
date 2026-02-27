const makeQuotaError = () => {
  const error = new Error("exceeded quota");
  (error as Error & { name: string }).name = "QuotaExceededError";
  return error;
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
