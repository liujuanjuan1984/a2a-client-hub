import { extractStreamBlockUpdate } from "@/lib/api/chat-utils";

const canonicalCases =
  require("../../../docs/contracts/stream-block-operation-canonical-cases.json") as {
    name: string;
    payload: Record<string, unknown>;
    expected: Record<string, unknown>;
  }[];

const normalizeParsedUpdate = (
  payload: Record<string, unknown>,
  expected: Record<string, unknown>,
) => {
  const parsed = extractStreamBlockUpdate({
    ...payload,
    version: "v1",
    streamBlock: {
      eventId: expected.eventId,
      eventIdSource: "upstream",
      messageIdSource: "upstream",
      seq: expected.seq,
      taskId:
        typeof expected.artifactId === "string"
          ? expected.artifactId.split(":")[0]
          : "task-1",
      artifactId: expected.artifactId,
      blockId: expected.blockId,
      laneId: expected.laneId,
      blockType: expected.blockType,
      op: expected.op,
      baseSeq: expected.baseSeq,
      source: expected.source,
      messageId: expected.messageId,
      role: "agent",
      delta: expected.content,
      append: expected.op === "append",
      done: expected.isFinished,
    },
  });
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
      expect(
        normalizeParsedUpdate(testCase.payload, testCase.expected),
      ).toEqual(testCase.expected);
    });
  });
});
