(globalThis as any).__DEV__ = true;
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
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
