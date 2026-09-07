const React = require("react");
const jsxRuntime = require("react/jsx-runtime");

module.exports = {
  ...jsxRuntime,
  createInteropElement: React.createElement,
};
