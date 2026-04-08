const rnPreset = require("react-native/jest-preset");

module.exports = {
  ...rnPreset,
  coverageProvider: "v8",
  testMatch: ["**/?(*.)+(spec|test).[tj]s?(x)"],
  collectCoverage: true,
  coverageThreshold: {
    global: {
      branches: 20,
      functions: 25,
      lines: 30,
      statements: 30,
    },
  },
  setupFiles: ["<rootDir>/jest.preload.ts"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  transformIgnorePatterns: [
    "/node_modules/(?!((jest-)?react-native|@react-native(-community)?)|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|@unimodules/.*|unimodules|sentry-expo|native-base|react-native-svg)",
  ],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
    "^@app/(.*)$": "<rootDir>/app/$1",
    "^@components/(.*)$": "<rootDir>/components/$1",
    "^@hooks/(.*)$": "<rootDir>/hooks/$1",
    "^@lib/(.*)$": "<rootDir>/lib/$1",
    "^@screens/(.*)$": "<rootDir>/screens/$1",
    "^@services/(.*)$": "<rootDir>/services/$1",
    "^@store/(.*)$": "<rootDir>/store/$1",
    "^react-native-css-interop(?:/(.*))?$":
      "<rootDir>/jest/react-native-css-interop-mock.js",
  },
};
