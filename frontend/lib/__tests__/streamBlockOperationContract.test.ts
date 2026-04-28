import { extractStreamBlockUpdate } from "@/lib/api/chat-utils";

const canonicalCases =
  require("../../../docs/contracts/stream-block-operation-canonical-cases.json") as {
    name: string;
    payload: Record<string, unknown>;
    expected: Record<string, unknown>;
  }[];

const normalizeParsedUpdate = (payload: Record<string, unknown>) => {
  const parsed = extractStreamBlockUpdate(payload);
  expect(parsed).not.toBeNull();
  return {
    eventId: parsed?.eventId ?? null,
    seq: parsed?.seq ?? null,
    messageId: parsed?.messageId ?? null,
    artifactId: parsed?.artifactId ?? null,
    blockId: parsed?.blockId ?? null,
    laneId: parsed?.laneId ?? null,
    blockType: parsed?.blockType ?? null,
    op: parsed?.op ?? null,
    content: parsed?.delta ?? null,
    baseSeq: parsed?.baseSeq ?? null,
    isFinished: parsed?.done ?? null,
    source: parsed?.source ?? null,
  };
};

describe("stream block operation contract", () => {
  it("matches the shared canonical cases", () => {
    canonicalCases.forEach((testCase) => {
      expect(normalizeParsedUpdate(testCase.payload)).toEqual(
        testCase.expected,
      );
    });
  });
});
