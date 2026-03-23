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
    event_id: parsed?.eventId ?? null,
    seq: parsed?.seq ?? null,
    message_id: parsed?.messageId ?? null,
    artifact_id: parsed?.artifactId ?? null,
    block_id: parsed?.blockId ?? null,
    lane_id: parsed?.laneId ?? null,
    block_type: parsed?.blockType ?? null,
    op: parsed?.op ?? null,
    content: parsed?.delta ?? null,
    base_seq: parsed?.baseSeq ?? null,
    is_finished: parsed?.done ?? null,
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
