import { serializeStructuredStreamData } from "@/lib/api/chat-utils";

const serializationCases =
  require("../../../docs/contracts/structured-block-stable-serialization-cases.json") as {
    name: string;
    value: unknown;
    expected: string | null;
  }[];

describe("structured block stable serialization contract", () => {
  it("matches the shared contract cases", () => {
    serializationCases.forEach((testCase) => {
      expect(serializeStructuredStreamData(testCase.value)).toBe(
        testCase.expected,
      );
    });
  });
});
