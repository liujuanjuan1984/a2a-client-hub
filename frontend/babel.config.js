module.exports = function (api) {
  const isTest = api.env("test");
  api.cache.using(() => isTest);
  return {
    // NativeWind's Babel plugin rewrites React.createElement even inside
    // @react-native/* files, which breaks RN 0.86's Jest preset. Keep tests on
    // the stock JSX transform; className styling is not asserted in tests.
    presets: isTest
      ? ["babel-preset-expo"]
      : ["babel-preset-expo", "nativewind/babel"],
  };
};
