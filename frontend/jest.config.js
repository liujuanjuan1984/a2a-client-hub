module.exports = {
  preset: "jest-expo",
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
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  moduleNameMapper: {
    "^react-native-css-interop(?:/(.*))?$":
      "<rootDir>/jest/react-native-css-interop-mock.js",
  },
};
