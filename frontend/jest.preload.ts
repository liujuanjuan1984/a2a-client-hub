(globalThis as any).__DEV__ = true;
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
(globalThis as any).IS_REACT_NATIVE_TEST_ENVIRONMENT = true;
(globalThis as any).__fbBatchedBridgeConfig = (globalThis as any)
  .__fbBatchedBridgeConfig ?? {
  remoteModuleConfig: [],
  localModulesConfig: [],
};
(globalThis as any).__turboModuleProxy =
  (globalThis as any).__turboModuleProxy ??
  ((name: string) => {
    if (name === "PlatformConstants") {
      return {
        getConstants: () => ({
          forceTouchAvailable: false,
          interfaceIdiom: "phone",
          reactNativeVersion: { major: 0, minor: 81, patch: 0 },
        }),
      };
    }
    return {
      getConstants: () => ({}),
    };
  });

const NativeModules = require("react-native/Libraries/BatchedBridge/NativeModules");
const originalTurboModuleProxy = (globalThis as any).__turboModuleProxy;

const ensureEmitterModule = (
  moduleName: string,
  moduleDefaults: Record<string, unknown> = {},
) => {
  const nativeModule = (NativeModules[moduleName] ?? {}) as Record<
    string,
    unknown
  >;

  if (typeof nativeModule.addListener !== "function") {
    nativeModule.addListener = jest.fn();
  }
  if (typeof nativeModule.removeListeners !== "function") {
    nativeModule.removeListeners = jest.fn();
  }

  for (const [key, value] of Object.entries(moduleDefaults)) {
    if (typeof nativeModule[key] === "undefined") {
      nativeModule[key] = value;
    }
  }

  NativeModules[moduleName] = nativeModule;
  return nativeModule;
};

NativeModules.KeyboardObserver = NativeModules.KeyboardObserver ?? {
  addListener: jest.fn(),
  removeListeners: jest.fn(),
};

const linkingManagerModule = ensureEmitterModule("LinkingManager", {
  getInitialURL: jest.fn(async () => null),
  canOpenURL: jest.fn(async () => false),
  openURL: jest.fn(async () => undefined),
  openSettings: jest.fn(async () => undefined),
});

const modalManagerModule = ensureEmitterModule("ModalManager");

(globalThis as any).__turboModuleProxy = (name: string) => {
  if (name === "KeyboardObserver") {
    return NativeModules.KeyboardObserver;
  }
  if (name === "LinkingManager") {
    return linkingManagerModule;
  }
  if (name === "ModalManager") {
    return modalManagerModule;
  }
  return originalTurboModuleProxy(name);
};

NativeModules.NativeUnimoduleProxy =
  NativeModules.NativeUnimoduleProxy ?? ({ viewManagersMetadata: {} } as any);
NativeModules.UIManager = NativeModules.UIManager ?? ({} as any);
NativeModules.PlatformConstants =
  NativeModules.PlatformConstants ??
  ({
    forceTouchAvailable: false,
    interfaceIdiom: "phone",
    reactNativeVersion: { major: 0, minor: 81, patch: 0 },
    Dimensions: {
      window: { width: 375, height: 812, scale: 2, fontScale: 2 },
      screen: { width: 375, height: 812, scale: 2, fontScale: 2 },
    },
  } as any);
NativeModules.Appearance = NativeModules.Appearance ?? {
  getColorScheme: () => "light",
  addListener: () => {},
  removeListeners: () => {},
};

(globalThis as any).expo =
  (globalThis as any).expo ??
  ({
    EventEmitter: class {},
    NativeModule: class {},
    SharedObject: class {},
  } as any);
