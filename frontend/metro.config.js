const path = require("path");
const { resolve } = require("metro-resolver");
const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");

const config = getDefaultConfig(__dirname);
config.resolver = config.resolver ?? {};

const aliasModules = {
  zustand: path.join(__dirname, "node_modules", "zustand", "index.js"),
  "zustand/middleware": path.join(
    __dirname,
    "node_modules",
    "zustand",
    "middleware.js",
  ),
};

const defaultResolveRequest =
  config.resolver.resolveRequest ??
  ((context, moduleName, platform) => resolve(context, moduleName, platform));

config.resolver.resolveRequest = (context, moduleName, platform) => {
  const aliasPath = aliasModules[moduleName];
  if (aliasPath) {
    return {
      filePath: aliasPath,
      type: "sourceFile",
    };
  }
  return defaultResolveRequest(context, moduleName, platform);
};

module.exports = withNativeWind(config, {
  input: "./global.css",
});
