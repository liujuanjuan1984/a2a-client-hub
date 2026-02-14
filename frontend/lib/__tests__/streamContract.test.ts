import {
  applyStreamBlockUpdate,
  extractStreamBlockUpdate,
  finalizeMessageBlocks,
  projectPrimaryTextContent,
  type MessageBlock,
  type StreamBlockUpdate,
} from "@/lib/api/chat-utils";

const buildBlockUpdatePayload = (input: {
  contentType: string;
  delta: string;
  artifactId: string;
  taskId?: string;
  messageId?: string;
  append?: boolean;
  source?: string;
  lastChunk?: boolean;
}) => ({
  kind: "artifact-update",
  task_id: input.taskId ?? "task-1",
  message_id: input.messageId ?? "msg-1",
  append: input.append ?? true,
  lastChunk: input.lastChunk ?? false,
  artifact: {
    artifact_id: input.artifactId,
    parts: [{ kind: "text", text: input.delta }],
    metadata: {
      opencode: {
        content_type: input.contentType,
        source: input.source ?? "stream",
      },
    },
  },
});

const mustParse = (payload: Record<string, unknown>): StreamBlockUpdate => {
  const parsed = extractStreamBlockUpdate(payload);
  expect(parsed).not.toBeNull();
  return parsed as StreamBlockUpdate;
};

describe("block-based stream parser and reducer", () => {
  it("appends when incoming content_type matches the active block", () => {
    let blocks: MessageBlock[] | undefined = undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          contentType: "reasoning",
          delta: "thinking",
          artifactId: "task-1:stream:reasoning",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          contentType: "reasoning",
          delta: " more",
          artifactId: "task-1:stream:reasoning",
        }),
      ),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks?.[0]?.type).toBe("reasoning");
    expect(blocks?.[0]?.content).toBe("thinking more");
  });

  it("creates a new block and finalizes previous block when type switches", () => {
    let blocks: MessageBlock[] | undefined = undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          contentType: "reasoning",
          delta: "plan",
          artifactId: "task-1:stream:reasoning",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          contentType: "tool_call",
          delta: "search()",
          artifactId: "task-1:stream:tool",
        }),
      ),
    );

    expect(blocks).toHaveLength(2);
    expect(blocks?.[0]?.type).toBe("reasoning");
    expect(blocks?.[0]?.isFinished).toBe(true);
    expect(blocks?.[1]?.type).toBe("tool_call");
  });

  it("maps final_answer to text and projects only text blocks into message content", () => {
    let blocks: MessageBlock[] | undefined = undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          contentType: "final_answer",
          delta: "Hello",
          artifactId: "task-1:stream:text",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          contentType: "reasoning",
          delta: "thought",
          artifactId: "task-1:stream:reasoning",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          contentType: "text",
          delta: " world",
          artifactId: "task-1:stream:text",
        }),
      ),
    );

    expect(projectPrimaryTextContent(blocks)).toBe("Hello world");
  });

  it("supports overwrite semantics when append=false or final_snapshot arrives", () => {
    let blocks: MessageBlock[] | undefined = undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          contentType: "text",
          delta: "abc",
          artifactId: "task-2:stream:text",
          append: true,
          taskId: "task-2",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          contentType: "text",
          delta: "reset",
          artifactId: "task-2:stream:text",
          append: false,
          source: "final_snapshot",
          taskId: "task-2",
        }),
      ),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks?.[0]?.content).toBe("reset");
  });

  it("keeps unknown content_type as fallback blocks", () => {
    const parsed = extractStreamBlockUpdate(
      buildBlockUpdatePayload({
        contentType: "custom_phase",
        delta: "custom content",
        artifactId: "task-1:stream:custom",
      }),
    );
    expect(parsed?.contentType).toBe("custom_phase");
  });

  it("ignores chunks without message_id", () => {
    const payload = buildBlockUpdatePayload({
      contentType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
      messageId: "",
    }) as Record<string, unknown>;
    delete payload.message_id;
    const parsed = extractStreamBlockUpdate(payload);
    expect(parsed).toBeNull();
  });

  it("finalizes the active block on stream completion", () => {
    const blocks: MessageBlock[] = [
      {
        id: "blk-1",
        type: "reasoning",
        content: "thinking",
        isFinished: false,
        createdAt: "2026-02-14T00:00:00.000Z",
        updatedAt: "2026-02-14T00:00:00.000Z",
      },
    ];
    const finalized = finalizeMessageBlocks(blocks);
    expect(finalized?.[0]?.isFinished).toBe(true);
  });
});
