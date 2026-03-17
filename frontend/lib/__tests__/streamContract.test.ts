import {
  applyLoadedBlockDetail,
  applyStreamBlockUpdate,
  buildInterruptEventBlockUpdate,
  extractSessionMeta,
  extractRuntimeStatus,
  extractRuntimeStatusEvent,
  extractStreamBlockUpdate,
  finalizeMessageBlocks,
  projectPrimaryTextContent,
  type MessageBlock,
  type StreamBlockUpdate,
} from "@/lib/api/chat-utils";

const buildBlockUpdatePayload = (input: {
  blockType: "text" | "reasoning" | "tool_call" | "interrupt_event";
  delta: string;
  artifactId: string;
  taskId?: string;
  messageId?: string;
  eventId?: string;
  seq?: number;
  append?: boolean;
  source?: string;
  lastChunk?: boolean;
}) => {
  const payload: Record<string, unknown> = {
    kind: "artifact-update",
    task_id: input.taskId ?? "task-1",
    message_id: input.messageId ?? "msg-1",
    event_id: input.eventId ?? "evt-1",
    append: input.append ?? true,
    lastChunk: input.lastChunk ?? false,
    artifact: {
      artifact_id: input.artifactId,
      parts: [{ kind: "text", text: input.delta }],
      metadata: {
        block_type: input.blockType,
        source: input.source ?? "stream",
      },
    },
  };
  if (input.seq !== undefined) {
    payload.seq = input.seq;
  }
  return payload;
};

const mustParse = (payload: Record<string, unknown>): StreamBlockUpdate => {
  const parsed = extractStreamBlockUpdate(payload);
  expect(parsed).not.toBeNull();
  return parsed as StreamBlockUpdate;
};

describe("block-based stream parser and reducer", () => {
  it("appends when incoming block_type matches the active block", () => {
    let blocks: MessageBlock[] | undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "reasoning",
          delta: "thinking",
          artifactId: "task-1:stream:reasoning",
          seq: 1,
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
          seq: 2,
        }),
      ),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks?.[0]?.type).toBe("reasoning");
    expect(blocks?.[0]?.content).toBe("thinking more");
  });

  it("creates a new block and finalizes previous block when type switches", () => {
    let blocks: MessageBlock[] | undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "reasoning",
          delta: "plan",
          artifactId: "task-1:stream:reasoning",
          seq: 1,
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
          seq: 2,
        }),
      ),
    );

    expect(blocks).toHaveLength(2);
    expect(blocks?.[0]?.isFinished).toBe(true);
    expect(blocks?.[1]?.type).toBe("tool_call");
  });

  it("projects only text blocks into message content", () => {
    let blocks: MessageBlock[] | undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          delta: "Hello",
          artifactId: "task-1:stream:text",
          seq: 1,
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
          seq: 2,
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
          seq: 3,
        }),
      ),
    );

    expect(projectPrimaryTextContent(blocks)).toBe("Hello world");
  });

  it("keeps interrupt_event blocks out of projected message content", () => {
    const blocks = applyStreamBlockUpdate(
      undefined,
      buildInterruptEventBlockUpdate({
        messageId: "msg-interrupt-1",
        interrupt: {
          requestId: "perm-1",
          type: "permission",
          phase: "asked",
          details: {
            permission: "read",
            patterns: ["/repo/.env"],
            displayMessage: null,
          },
        },
      }),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks?.[0]?.type).toBe("interrupt_event");
    expect(blocks?.[0]?.content).toBe(
      "Agent requested authorization: read.\nTargets: /repo/.env",
    );
    expect(projectPrimaryTextContent(blocks)).toBe("");
  });

  it("prefers richer permission display text when building interrupt_event blocks", () => {
    const update = buildInterruptEventBlockUpdate({
      messageId: "msg-interrupt-rich-permission",
      interrupt: {
        requestId: "perm-rich-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "approval",
          patterns: ["/repo/.env"],
          displayMessage: "Agent wants to read the environment file.",
        },
      },
    });

    expect(update.delta).toBe(
      "Agent wants to read the environment file.\nTargets: /repo/.env",
    );
  });

  it("keeps question descriptions when building interrupt_event blocks", () => {
    const update = buildInterruptEventBlockUpdate({
      messageId: "msg-interrupt-rich-question",
      interrupt: {
        requestId: "q-rich-1",
        type: "question",
        phase: "asked",
        details: {
          displayMessage: "Please confirm how the agent should continue.",
          questions: [
            {
              header: "Approval",
              question: "Proceed with deployment?",
              description: "This will update the production service.",
              options: [{ label: "Yes", value: "yes", description: null }],
            },
          ],
        },
      },
    });

    expect(update.delta).toBe(
      "Please confirm how the agent should continue.\n" +
        "Question: Proceed with deployment?\n" +
        "Details: This will update the production service.",
    );
  });

  it("supports overwrite semantics when append=false or final_snapshot arrives", () => {
    let blocks: MessageBlock[] | undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          delta: "abc",
          artifactId: "task-2:stream:text",
          append: true,
          taskId: "task-2",
          seq: 1,
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
          seq: 2,
        }),
      ),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks?.[0]?.content).toBe("reset");
  });

  it("syncs message content when loading text block details", () => {
    const message = {
      content: "",
      blocks: [
        {
          id: "block-1",
          type: "text",
          content: "",
          isFinished: false,
          createdAt: "2026-03-17T10:00:00.000Z",
          updatedAt: "2026-03-17T10:00:00.000Z",
        },
        {
          id: "block-2",
          type: "reasoning",
          content: "plan",
          isFinished: true,
          createdAt: "2026-03-17T10:00:01.000Z",
          updatedAt: "2026-03-17T10:00:01.000Z",
        },
      ],
    };

    const next = applyLoadedBlockDetail(message, {
      blockId: "block-1",
      type: "text",
      content: "Loaded text",
      isFinished: true,
    });

    expect(next.content).toBe("Loaded text");
    expect(next.blocks?.[0]).toMatchObject({
      id: "block-1",
      type: "text",
      content: "Loaded text",
      isFinished: true,
    });
  });

  it("preserves existing content when loading non-text block details", () => {
    const message = {
      content: "Visible text",
      blocks: [
        {
          id: "block-1",
          type: "text",
          content: "Visible text",
          isFinished: true,
          createdAt: "2026-03-17T10:00:00.000Z",
          updatedAt: "2026-03-17T10:00:00.000Z",
        },
        {
          id: "block-2",
          type: "tool_call",
          content: "",
          isFinished: false,
          createdAt: "2026-03-17T10:00:01.000Z",
          updatedAt: "2026-03-17T10:00:01.000Z",
        },
      ],
    };

    const next = applyLoadedBlockDetail(message, {
      blockId: "block-2",
      type: "tool_call",
      content: '{"tool":"search"}',
      isFinished: true,
    });

    expect(next.content).toBe("Visible text");
    expect(next.blocks?.[1]).toMatchObject({
      id: "block-2",
      type: "tool_call",
      content: '{"tool":"search"}',
      isFinished: true,
    });
  });

  it("parses block_type from canonical metadata", () => {
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
          block_type: "text",
        },
      },
    });
    expect(parsed?.blockType).toBe("text");
    expect(parsed?.eventIdSource).toBe("upstream");
  });

  it("prefers standard metadata.block_type", () => {
    const parsed = extractStreamBlockUpdate({
      kind: "artifact-update",
      task_id: "task-9",
      message_id: "msg-9",
      event_id: "evt-9",
      artifact: {
        artifact_id: "task-9:stream",
        parts: [{ kind: "text", text: "thinking" }],
        metadata: {
          block_type: "reasoning",
        },
      },
    });
    expect(parsed?.blockType).toBe("reasoning");
  });

  it("prefers shared.stream metadata for tool_call blocks carried in text parts", () => {
    const parsed = extractStreamBlockUpdate({
      kind: "artifact-update",
      taskId: "task-10",
      artifact: {
        artifactId: "task-10:stream",
        parts: [{ kind: "text", text: '{"tool":"bash","status":"running"}' }],
        metadata: {
          shared: {
            stream: {
              block_type: "tool_call",
              source: "tool_part_update",
              message_id: "msg-shared",
              event_id: "evt-shared",
              sequence: 10,
            },
          },
        },
      },
    });
    expect(parsed?.blockType).toBe("tool_call");
    expect(parsed?.messageId).toBe("msg-shared");
    expect(parsed?.eventId).toBe("evt-shared");
    expect(parsed?.seq).toBe(10);
    expect(parsed?.source).toBe("tool_part_update");
  });

  it("parses interrupt_event blocks carried in artifact metadata", () => {
    const parsed = extractStreamBlockUpdate({
      kind: "artifact-update",
      message_id: "msg-interrupt-2",
      event_id: "evt-interrupt-2",
      seq: 8,
      append: false,
      artifact: {
        artifact_id: "artifact-interrupt-2",
        parts: [
          {
            kind: "text",
            text: "Agent requested additional input: Proceed?",
          },
        ],
        metadata: {
          block_type: "interrupt_event",
          source: "interrupt_lifecycle",
        },
      },
    });

    expect(parsed).toMatchObject({
      blockType: "interrupt_event",
      delta: "Agent requested additional input: Proceed?",
      messageId: "msg-interrupt-2",
      source: "interrupt_lifecycle",
      append: false,
      done: false,
    });
  });

  it("parses tool_call blocks carried in data parts", () => {
    const parsed = extractStreamBlockUpdate({
      kind: "artifact-update",
      taskId: "task-10",
      artifact: {
        artifactId: "task-10:stream",
        parts: [
          {
            kind: "data",
            data: {
              call_id: "call-1",
              tool: "read",
              status: "pending",
              input: {},
            },
          },
        ],
        metadata: {
          shared: {
            stream: {
              block_type: "tool_call",
              source: "tool_part_update",
              message_id: "msg-data",
              event_id: "evt-data",
              sequence: 11,
            },
          },
        },
      },
    });
    expect(parsed?.blockType).toBe("tool_call");
    expect(parsed?.delta).toBe(
      '{"call_id":"call-1","input":{},"status":"pending","tool":"read"}',
    );
    expect(parsed?.messageId).toBe("msg-data");
    expect(parsed?.eventId).toBe("evt-data");
    expect(parsed?.seq).toBe(11);
  });

  it("infers text block type when explicit metadata is missing", () => {
    const parsed = extractStreamBlockUpdate({
      kind: "artifact-update",
      taskId: "task-9",
      artifact: {
        artifactId: "task-9:stream",
        parts: [{ kind: "text", text: "hello" }],
      },
    });
    expect(parsed?.blockType).toBe("text");
    expect(parsed?.messageId).toBe("task:task-9");
  });

  it("accepts text parts that use type/content shape", () => {
    const parsed = extractStreamBlockUpdate({
      kind: "artifact-update",
      taskId: "task-11",
      artifact: {
        artifactId: "task-11:stream",
        parts: [{ type: "text", content: "hello" }],
      },
    });
    expect(parsed?.blockType).toBe("text");
    expect(parsed?.delta).toBe("hello");
  });

  it("parses chunk when taskId is missing but messageId exists", () => {
    const parsed = extractStreamBlockUpdate({
      kind: "artifact-update",
      message_id: "msg-only-1",
      artifact: {
        artifact_id: "stream-1",
        parts: [{ kind: "text", text: "hello" }],
      },
    });
    expect(parsed?.messageId).toBe("msg-only-1");
    expect(parsed?.taskId).toBe("msg-only-1");
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
          block_type: "custom_phase",
        },
      },
    });
    expect(parsed).toBeNull();
  });

  it("falls back to task-based message id when message_id is missing", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
      messageId: "",
    }) as Record<string, unknown>;
    delete payload.message_id;
    const parsed = extractStreamBlockUpdate(payload);
    expect(parsed?.messageId).toBe("task:task-1");
  });

  it("uses seq-based fallback when event_id is missing", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
      seq: 7,
    }) as Record<string, unknown>;
    delete payload.event_id;
    const parsed = extractStreamBlockUpdate(payload);
    expect(parsed?.eventId).toBe("seq:msg-1:7");
    expect(parsed?.eventIdSource).toBe("fallback_seq");
  });

  it("accepts chunks using camelCase message/event fields", () => {
    const payload = {
      kind: "artifact-update",
      task_id: "task-1",
      messageId: "msg-camel",
      eventId: "evt-camel",
      artifact: {
        artifact_id: "task-1:stream",
        parts: [{ kind: "text", text: "hello" }],
        metadata: {
          block_type: "text",
        },
      },
    };
    const parsed = extractStreamBlockUpdate(payload);
    expect(parsed?.messageId).toBe("msg-camel");
    expect(parsed?.eventId).toBe("evt-camel");
  });

  it("accepts chunks without seq and marks seq as null", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
      seq: undefined,
    });
    const parsed = extractStreamBlockUpdate(payload);
    expect(parsed?.seq).toBeNull();
    expect(parsed?.eventId).toBe("evt-1");
    expect(parsed?.eventIdSource).toBe("upstream");
  });

  it("uses chunk-based fallback when both seq and event_id are missing", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
      seq: undefined,
    }) as Record<string, unknown>;
    delete payload.event_id;
    const parsed = extractStreamBlockUpdate(payload);
    expect(parsed?.seq).toBeNull();
    expect(parsed?.eventId).toBe("chunk:msg-1:task-1:stream");
    expect(parsed?.eventIdSource).toBe("fallback_chunk");
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
      interrupt: null,
    });
  });

  it("returns null runtime status event for non-status payload", () => {
    expect(extractRuntimeStatusEvent({ kind: "artifact-update" })).toBeNull();
  });

  it("parses permission interrupt metadata from status-update", () => {
    const payload = {
      kind: "status-update",
      status: { state: "input-required" },
      metadata: {
        shared: {
          interrupt: {
            request_id: "perm-1",
            type: "permission",
            details: {
              permission: "read",
              patterns: ["/repo/.env"],
            },
          },
        },
      },
    };
    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "input-required",
      isFinal: false,
      interrupt: {
        requestId: "perm-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "read",
          patterns: ["/repo/.env"],
          displayMessage: null,
        },
      },
    });
  });

  it("parses richer permission interrupt display text from nested metadata", () => {
    const payload = {
      kind: "status-update",
      status: { state: "input-required" },
      metadata: {
        shared: {
          interrupt: {
            request_id: "perm-2",
            type: "permission",
            details: {
              permission: "approval",
              patterns: ["/repo/.env"],
              request: {
                description: "Agent wants to read the environment file.",
              },
            },
          },
        },
      },
    };
    expect(extractRuntimeStatusEvent(payload)?.interrupt).toEqual({
      requestId: "perm-2",
      type: "permission",
      phase: "asked",
      details: {
        permission: "approval",
        patterns: ["/repo/.env"],
        displayMessage: "Agent wants to read the environment file.",
      },
    });
  });

  it("parses question interrupt metadata from status-update", () => {
    const payload = {
      kind: "status-update",
      status: { state: "input-required" },
      metadata: {
        shared: {
          interrupt: {
            request_id: "q-1",
            type: "question",
            details: {
              questions: [
                {
                  header: "Confirm",
                  question: "Proceed?",
                  options: [{ label: "Yes", value: "yes" }],
                },
              ],
            },
          },
        },
      },
    };
    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "input-required",
      isFinal: false,
      interrupt: {
        requestId: "q-1",
        type: "question",
        phase: "asked",
        details: {
          displayMessage: null,
          questions: [
            {
              header: "Confirm",
              question: "Proceed?",
              description: null,
              options: [{ label: "Yes", value: "yes", description: null }],
            },
          ],
        },
      },
    });
  });

  it("parses richer question interrupt metadata from nested fields", () => {
    const payload = {
      kind: "status-update",
      status: { state: "input-required" },
      metadata: {
        shared: {
          interrupt: {
            request_id: "q-2",
            type: "question",
            details: {
              description: "Please confirm how the agent should continue.",
              questions: [
                {
                  title: "Approval",
                  prompt: "Proceed with deployment?",
                  description: "This will update the production service.",
                  options: [{ label: "Yes", value: "yes" }],
                },
              ],
            },
          },
        },
      },
    };
    expect(extractRuntimeStatusEvent(payload)?.interrupt).toEqual({
      requestId: "q-2",
      type: "question",
      phase: "asked",
      details: {
        displayMessage: "Please confirm how the agent should continue.",
        questions: [
          {
            header: "Approval",
            question: "Proceed with deployment?",
            description: "This will update the production service.",
            options: [{ label: "Yes", value: "yes", description: null }],
          },
        ],
      },
    });
  });

  it("parses resolved interrupt metadata from non-input-required status-update", () => {
    const payload = {
      kind: "status-update",
      status: { state: "working" },
      metadata: {
        shared: {
          interrupt: {
            request_id: "q-1",
            type: "question",
            phase: "resolved",
            resolution: "rejected",
          },
        },
      },
    };
    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "working",
      isFinal: false,
      interrupt: {
        requestId: "q-1",
        type: "question",
        phase: "resolved",
        resolution: "rejected",
      },
    });
  });

  it("extracts external session from canonical shared session metadata", () => {
    const meta = extractSessionMeta({
      kind: "status-update",
      final: true,
      metadata: {
        provider: "opencode",
        shared: {
          session: {
            id: "ses_upstream_1",
          },
        },
      },
    });
    expect(meta.provider).toBe("opencode");
    expect(meta.externalSessionId).toBe("ses_upstream_1");
  });

  it("falls back to legacy root session metadata when shared session metadata is missing", () => {
    const meta = extractSessionMeta({
      kind: "status-update",
      final: true,
      metadata: {
        provider: "opencode",
        externalSessionId: "ses_upstream_1",
      },
    });
    expect(meta.provider).toBe("opencode");
    expect(meta.externalSessionId).toBe("ses_upstream_1");
  });

  it("falls back to legacy interrupt metadata when shared interrupt metadata is missing", () => {
    const payload = {
      kind: "status-update",
      status: { state: "input-required" },
      metadata: {
        interrupt: {
          request_id: "perm-legacy-1",
          type: "permission",
          details: {
            permission: "read",
            patterns: ["/repo/.env"],
          },
        },
      },
    };
    expect(extractRuntimeStatusEvent(payload)?.interrupt).toEqual({
      requestId: "perm-legacy-1",
      type: "permission",
      phase: "asked",
      details: {
        permission: "read",
        patterns: ["/repo/.env"],
        displayMessage: null,
      },
    });
  });
});
