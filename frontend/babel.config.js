module.exports = function (api) {
  const isTest = api.env("test");
  api.cache.using(() => isTest);
  return {
    presets: isTest
      ? ["babel-preset-expo"]
      : ["babel-preset-expo", "nativewind/babel"],
  };
};
