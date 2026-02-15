import {
  applyStreamBlockUpdate,
  extractRuntimeStatus,
  extractRuntimeStatusEvent,
  extractStreamBlockUpdate,
  finalizeMessageBlocks,
  projectPrimaryTextContent,
  type MessageBlock,
  type StreamBlockUpdate,
} from "@/lib/api/chat-utils";

const buildBlockUpdatePayload = (input: {
  blockType: "text" | "reasoning" | "tool_call";
  delta: string;
  artifactId: string;
  taskId?: string;
  messageId?: string;
  eventId?: string;
  seq?: number;
  append?: boolean;
  source?: string;
  lastChunk?: boolean;
}) => ({
  kind: "artifact-update",
  task_id: input.taskId ?? "task-1",
  message_id: input.messageId ?? "msg-1",
  event_id: input.eventId ?? "evt-1",
  seq: input.seq ?? 1,
  append: input.append ?? true,
  lastChunk: input.lastChunk ?? false,
  artifact: {
    artifact_id: input.artifactId,
    parts: [{ kind: "text", text: input.delta }],
    metadata: {
      opencode: {
        block_type: input.blockType,
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
  it("appends when incoming block_type matches the active block", () => {
    let blocks: MessageBlock[] | undefined = undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "reasoning",
          delta: "thinking",
          artifactId: "task-1:stream:reasoning",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "reasoning",
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
          blockType: "reasoning",
          delta: "plan",
          artifactId: "task-1:stream:reasoning",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "tool_call",
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

  it("projects only text blocks into message content", () => {
    let blocks: MessageBlock[] | undefined = undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          delta: "Hello",
          artifactId: "task-1:stream:text",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "reasoning",
          delta: "thought",
          artifactId: "task-1:stream:reasoning",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
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
          blockType: "text",
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
          blockType: "text",
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

  it("parses block_type from opencode metadata", () => {
    const parsed = extractStreamBlockUpdate({
      kind: "artifact-update",
      task_id: "task-9",
      message_id: "msg-9",
      event_id: "evt-9",
      seq: 9,
      artifact: {
        artifact_id: "task-9:stream",
        parts: [{ kind: "text", text: "hello" }],
        metadata: {
          opencode: {
            block_type: "text",
          },
        },
      },
    });
    expect(parsed?.blockType).toBe("text");
  });

  it("ignores unsupported block_type values", () => {
    const parsed = extractStreamBlockUpdate({
      kind: "artifact-update",
      task_id: "task-8",
      message_id: "msg-8",
      event_id: "evt-8",
      seq: 8,
      artifact: {
        artifact_id: "task-8:stream",
        parts: [{ kind: "text", text: "noop" }],
        metadata: {
          opencode: {
            block_type: "custom_phase",
          },
        },
      },
    });
    expect(parsed).toBeNull();
  });

  it("ignores chunks without message_id", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
      messageId: "",
    }) as Record<string, unknown>;
    delete payload.message_id;
    const parsed = extractStreamBlockUpdate(payload);
    expect(parsed).toBeNull();
  });

  it("ignores chunks without event_id", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
    }) as Record<string, unknown>;
    delete payload.event_id;
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

  it("parses status-update terminal signal", () => {
    const payload = {
      kind: "status-update",
      status: { state: "input_required" },
      final: true,
    };

    expect(extractRuntimeStatus(payload)).toBe("input_required");
    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "input_required",
      isFinal: true,
    });
  });

  it("returns null runtime status event for non-status payload", () => {
    expect(extractRuntimeStatusEvent({ kind: "artifact-update" })).toBeNull();
  });
});
