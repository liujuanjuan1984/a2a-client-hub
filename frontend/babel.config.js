const isSourceFile = (filename) =>
  Boolean(filename) && !/node_modules[\\/]/.test(filename);

module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
    // NativeWind rewrites React.createElement calls; applying it only to
    // project source keeps @react-native/* Jest preset internals untouched.
    overrides: [{ test: isSourceFile, presets: ["nativewind/babel"] }],
  };
};
