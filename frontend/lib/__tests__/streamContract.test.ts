import {
  DEFAULT_RUNTIME_STATUS_CONTRACT,
  applyLoadedBlockDetail,
  applyStreamBlockUpdate,
  buildInterruptEventBlockUpdate,
  extractSessionMeta,
  extractRuntimeStatusEvent,
  extractStreamBlockUpdate,
  finalizeMessageBlocks,
  normalizeRuntimeState,
  projectPrimaryTextContent,
  type MessageBlock,
  type StreamBlockUpdate,
} from "@/lib/api/chat-utils";

const interruptLifecycleMessageCases =
  require("../../../docs/contracts/interrupt-lifecycle-message-cases.json") as {
    name: string;
    code: string;
    event: Record<string, unknown>;
    content: string;
  }[];

const buildStatusUpdatePayload = (input: {
  state: string;
  seq?: number;
  messageId?: string;
  completionPhase?: string;
  interrupt?: Record<string, unknown>;
}) => {
  const canonicalInterrupt = buildCanonicalInterrupt(input.interrupt);
  return {
    statusUpdate: {
      status: { state: input.state },
      metadata: {
        shared: {
          ...(input.interrupt ? { interrupt: input.interrupt } : {}),
          stream: {
            ...(input.seq !== undefined ? { seq: input.seq } : {}),
            ...(input.messageId ? { messageId: input.messageId } : {}),
            ...(input.completionPhase
              ? { completionPhase: input.completionPhase }
              : {}),
          },
        },
      },
    },
    version: "v1",
    runtimeStatus: {
      state: normalizeRuntimeState(input.state),
      isFinal: DEFAULT_RUNTIME_STATUS_CONTRACT.terminalStates
        .map((item) => normalizeRuntimeState(item))
        .includes(normalizeRuntimeState(input.state)),
      ...(canonicalInterrupt ? { interrupt: canonicalInterrupt } : {}),
      ...(input.seq !== undefined ? { seq: input.seq } : {}),
      ...(input.completionPhase?.trim().toLowerCase() === "persisted"
        ? { completionPhase: "persisted" }
        : {}),
      ...(input.messageId ? { messageId: input.messageId } : {}),
    },
  };
};

const buildToolCallViewFromDelta = (delta: string | undefined) => {
  if (!delta) {
    return null;
  }
  try {
    const parsed = JSON.parse(delta) as Record<string, unknown>;
    const status = typeof parsed.status === "string" ? parsed.status : null;
    if (!status) {
      return null;
    }
    return {
      name:
        typeof parsed.name === "string"
          ? parsed.name
          : typeof parsed.tool === "string"
            ? parsed.tool
            : null,
      status,
      callId:
        typeof parsed.callId === "string"
          ? parsed.callId
          : typeof parsed.call_id === "string"
            ? parsed.call_id
            : null,
      arguments: parsed.arguments ?? parsed.input ?? null,
      result: parsed.result ?? parsed.output ?? null,
      error: parsed.error ?? null,
    };
  } catch {
    return null;
  }
};

const pickDisplayMessage = (
  details: Record<string, unknown> | null | undefined,
): string | null =>
  (typeof details?.displayMessage === "string" && details.displayMessage) ||
  (typeof details?.display_message === "string" && details.display_message) ||
  (typeof details?.description === "string" && details.description) ||
  (typeof (details?.request as { description?: unknown } | undefined)
    ?.description === "string" &&
    (details?.request as { description: string }).description) ||
  null;

const buildCanonicalInterrupt = (
  interrupt?: Record<string, unknown>,
): Record<string, unknown> | null => {
  if (!interrupt) {
    return null;
  }
  const requestId =
    typeof interrupt.requestId === "string" ? interrupt.requestId : null;
  const type = typeof interrupt.type === "string" ? interrupt.type : null;
  if (!requestId || !type) {
    return null;
  }
  const phase =
    typeof interrupt.phase === "string"
      ? interrupt.phase.toLowerCase()
      : "asked";
  if (phase === "resolved") {
    return {
      requestId,
      type,
      phase: "resolved",
      resolution:
        typeof interrupt.resolution === "string"
          ? interrupt.resolution
          : "replied",
      source: "stream",
    };
  }
  const details =
    interrupt.details && typeof interrupt.details === "object"
      ? (interrupt.details as Record<string, unknown>)
      : null;
  if (type === "permission") {
    return {
      requestId,
      type,
      phase: "asked",
      source: "stream",
      details: {
        permission:
          typeof details?.permission === "string" ? details.permission : null,
        patterns: Array.isArray(details?.patterns) ? details.patterns : [],
        displayMessage: pickDisplayMessage(details),
      },
    };
  }
  if (type === "permissions") {
    return {
      requestId,
      type,
      phase: "asked",
      source: "stream",
      details: {
        permissions:
          details?.permissions && typeof details.permissions === "object"
            ? details.permissions
            : null,
        displayMessage: pickDisplayMessage(details),
      },
    };
  }
  if (type === "elicitation") {
    return {
      requestId,
      type,
      phase: "asked",
      source: "stream",
      details: {
        displayMessage: pickDisplayMessage(details),
        serverName:
          typeof details?.serverName === "string" ? details.serverName : null,
        mode: typeof details?.mode === "string" ? details.mode : null,
        requestedSchema: details?.requestedSchema ?? null,
        url: typeof details?.url === "string" ? details.url : null,
        elicitationId:
          typeof details?.elicitationId === "string"
            ? details.elicitationId
            : null,
        meta:
          details?.meta && typeof details.meta === "object"
            ? details.meta
            : null,
      },
    };
  }
  const rawQuestions =
    Array.isArray(details?.questions) && details?.questions
      ? details.questions
      : [];
  return {
    requestId,
    type: "question",
    phase: "asked",
    source: "stream",
    details: {
      displayMessage: pickDisplayMessage(details),
      questions: rawQuestions.map((question) => {
        const record =
          question && typeof question === "object"
            ? (question as Record<string, unknown>)
            : {};
        const options = Array.isArray(record.options) ? record.options : [];
        return {
          header:
            typeof record.header === "string"
              ? record.header
              : typeof record.title === "string"
                ? record.title
                : null,
          question:
            typeof record.question === "string"
              ? record.question
              : typeof record.prompt === "string"
                ? record.prompt
                : typeof record.message === "string"
                  ? record.message
                  : "",
          description:
            typeof record.description === "string" ? record.description : null,
          options: options.map((option) => {
            const optionRecord =
              option && typeof option === "object"
                ? (option as Record<string, unknown>)
                : {};
            return {
              label:
                typeof optionRecord.label === "string"
                  ? optionRecord.label
                  : "",
              value:
                typeof optionRecord.value === "string"
                  ? optionRecord.value
                  : null,
              description:
                typeof optionRecord.description === "string"
                  ? optionRecord.description
                  : null,
            };
          }),
        };
      }),
    },
  };
};

const withHubStreamBlock = (
  payload: Record<string, unknown>,
  streamBlock: Record<string, unknown>,
) => ({
  ...payload,
  version: "v1",
  streamBlock,
});

const buildBlockUpdatePayload = (input: {
  blockType: "text" | "reasoning" | "tool_call" | "interrupt_event";
  delta?: string;
  artifactId: string;
  taskId?: string;
  messageId?: string;
  eventId?: string;
  seq?: number;
  append?: boolean;
  source?: string;
  lastChunk?: boolean;
  blockId?: string;
  laneId?: string;
  op?: "append" | "replace" | "finalize";
  baseSeq?: number;
  useSnakeCaseStreamHints?: boolean;
}) => {
  const streamIdentity = input.useSnakeCaseStreamHints
    ? {
        ...(input.messageId !== undefined
          ? { message_id: input.messageId }
          : { message_id: "msg-1" }),
        ...(input.eventId !== undefined
          ? { event_id: input.eventId }
          : { event_id: "evt-1" }),
        ...(input.seq !== undefined ? { sequence: input.seq } : {}),
        block_type: input.blockType,
      }
    : {
        ...(input.messageId !== undefined
          ? { messageId: input.messageId }
          : { messageId: "msg-1" }),
        ...(input.eventId !== undefined
          ? { eventId: input.eventId }
          : { eventId: "evt-1" }),
        ...(input.seq !== undefined ? { seq: input.seq } : {}),
      };
  const artifactMetadata: Record<string, unknown> = {
    source: input.source ?? "stream",
  };
  if (!input.useSnakeCaseStreamHints) {
    artifactMetadata.blockType = input.blockType;
  }
  if (input.blockId !== undefined) {
    artifactMetadata[input.useSnakeCaseStreamHints ? "block_id" : "blockId"] =
      input.blockId;
  }
  if (input.laneId !== undefined) {
    artifactMetadata[input.useSnakeCaseStreamHints ? "lane_id" : "laneId"] =
      input.laneId;
  }
  if (input.baseSeq !== undefined) {
    artifactMetadata[input.useSnakeCaseStreamHints ? "base_seq" : "baseSeq"] =
      input.baseSeq;
  }
  artifactMetadata.op =
    input.op ?? (input.append === false ? "replace" : "append");
  const payload: Record<string, unknown> = {
    artifactUpdate: {
      append: input.append ?? true,
      lastChunk: input.lastChunk ?? false,
      taskId: input.taskId ?? "task-1",
      artifact: {
        artifactId: input.artifactId,
        parts: input.delta !== undefined ? [{ text: input.delta }] : [],
        metadata: {
          ...artifactMetadata,
          shared: {
            stream: streamIdentity,
          },
        },
      },
    },
  };
  const laneId =
    input.laneId ??
    (input.blockType === "text" ? "primary_text" : input.blockType);
  const messageId = input.messageId ?? "msg-1";
  payload.version = "v1";
  payload.streamBlock = {
    eventId: input.eventId ?? "evt-1",
    eventIdSource: "upstream",
    messageIdSource: "upstream",
    ...(input.seq !== undefined ? { seq: input.seq } : {}),
    taskId: input.taskId ?? "task-1",
    artifactId: input.artifactId,
    blockId: input.blockId ?? `${messageId}:${laneId}`,
    laneId,
    blockType: input.blockType,
    op: input.op ?? (input.append === false ? "replace" : "append"),
    ...(input.baseSeq !== undefined ? { baseSeq: input.baseSeq } : {}),
    ...(input.source ? { source: input.source } : { source: "stream" }),
    messageId,
    role: "agent",
    delta: input.delta ?? "",
    append:
      input.append ?? !(input.op === "replace" || input.op === "finalize"),
    done: input.lastChunk ?? input.op === "finalize",
    toolCall:
      input.blockType === "tool_call"
        ? buildToolCallViewFromDelta(input.delta)
        : undefined,
  };
  return payload;
};

const mustParse = (payload: Record<string, unknown>): StreamBlockUpdate => {
  const parsed = extractStreamBlockUpdate(payload);
  expect(parsed).not.toBeNull();
  return parsed as StreamBlockUpdate;
};

describe("block-based stream parser and reducer", () => {
  it("appends when incoming blockType matches the active block", () => {
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

  it("derives distinct block ids when upstream reuses one artifact id across lanes", () => {
    const reasoning = mustParse(
      buildBlockUpdatePayload({
        blockType: "reasoning",
        delta: "thinking",
        artifactId: "task-1:stream",
        messageId: "msg-shared-lanes",
        seq: 1,
      }),
    );
    const text = mustParse(
      buildBlockUpdatePayload({
        blockType: "text",
        delta: "final answer",
        artifactId: "task-1:stream",
        messageId: "msg-shared-lanes",
        seq: 2,
      }),
    );

    expect(reasoning.blockId).toBe("msg-shared-lanes:reasoning");
    expect(text.blockId).toBe("msg-shared-lanes:primary_text");

    const blocks = applyStreamBlockUpdate(
      applyStreamBlockUpdate(undefined, reasoning),
      text,
    );
    expect(blocks).toHaveLength(2);
    expect(blocks?.[0]?.type).toBe("reasoning");
    expect(blocks?.[1]?.type).toBe("text");
  });

  it("parses snake_case stream-hints fields from shared stream metadata", () => {
    const parsed = mustParse(
      buildBlockUpdatePayload({
        blockType: "reasoning",
        delta: "thinking",
        artifactId: "task-1:stream:reasoning",
        messageId: "msg-snake-1",
        eventId: "evt-snake-1",
        seq: 9,
        useSnakeCaseStreamHints: true,
      }),
    );

    expect(parsed.blockType).toBe("reasoning");
    expect(parsed.messageId).toBe("msg-snake-1");
    expect(parsed.eventId).toBe("evt-snake-1");
    expect(parsed.seq).toBe(9);
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
      "Agent requested permission: read.\nTargets: /repo/.env",
    );
    expect(blocks?.[0]?.interrupt).toEqual({
      requestId: "perm-1",
      type: "permission",
      phase: "asked",
      details: {
        permission: "read",
        patterns: ["/repo/.env"],
        displayMessage: null,
      },
    });
    expect(projectPrimaryTextContent(blocks)).toBe("");
  });

  it("replaces an inline interrupt_event block when the same request resolves", () => {
    let blocks = applyStreamBlockUpdate(
      undefined,
      buildInterruptEventBlockUpdate({
        messageId: "msg-interrupt-2",
        interrupt: {
          requestId: "perm-2",
          type: "permission",
          phase: "asked",
          details: {
            permission: "write",
            patterns: ["/repo/config.yml"],
            displayMessage: null,
          },
        },
      }),
    );

    blocks = applyStreamBlockUpdate(
      blocks,
      buildInterruptEventBlockUpdate({
        messageId: "msg-interrupt-2",
        interrupt: {
          requestId: "perm-2",
          type: "permission",
          phase: "resolved",
          resolution: "replied",
        },
      }),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks?.[0]?.type).toBe("interrupt_event");
    expect(blocks?.[0]?.content).toBe(
      "Agent requested permission: write.\nTargets: /repo/config.yml",
    );
    expect(blocks?.[0]?.interrupt).toEqual({
      requestId: "perm-2",
      type: "permission",
      phase: "resolved",
      resolution: "replied",
    });
  });

  it("matches the shared interrupt lifecycle message contract cases", () => {
    const toRuntimeInterrupt = (
      event: Record<string, unknown>,
    ): Parameters<typeof buildInterruptEventBlockUpdate>[0]["interrupt"] => {
      const details =
        event.details && typeof event.details === "object"
          ? (event.details as Record<string, unknown>)
          : {};
      if (event.phase === "resolved") {
        return {
          requestId: String(event.requestId),
          type:
            event.type === "permission" ||
            event.type === "permissions" ||
            event.type === "elicitation"
              ? event.type
              : "question",
          phase: "resolved",
          resolution: event.resolution === "rejected" ? "rejected" : "replied",
        };
      }
      if (event.type === "permission") {
        return {
          requestId: String(event.requestId),
          type: "permission",
          phase: "asked",
          details: {
            permission:
              typeof details.permission === "string"
                ? details.permission
                : null,
            patterns: Array.isArray(details.patterns)
              ? details.patterns.filter(
                  (item): item is string => typeof item === "string",
                )
              : [],
            displayMessage:
              typeof details.displayMessage === "string"
                ? details.displayMessage
                : null,
          },
        };
      }
      if (event.type === "permissions") {
        return {
          requestId: String(event.requestId),
          type: "permissions",
          phase: "asked",
          details: {
            permissions:
              details.permissions && typeof details.permissions === "object"
                ? (details.permissions as Record<string, unknown>)
                : null,
            displayMessage:
              typeof details.displayMessage === "string"
                ? details.displayMessage
                : null,
          },
        };
      }
      if (event.type === "elicitation") {
        return {
          requestId: String(event.requestId),
          type: "elicitation",
          phase: "asked",
          details: {
            displayMessage:
              typeof details.displayMessage === "string"
                ? details.displayMessage
                : null,
            serverName:
              typeof details.serverName === "string"
                ? details.serverName
                : null,
            mode: typeof details.mode === "string" ? details.mode : null,
            requestedSchema: details.requestedSchema ?? null,
            url: typeof details.url === "string" ? details.url : null,
            elicitationId:
              typeof details.elicitationId === "string"
                ? details.elicitationId
                : null,
            meta:
              details.meta && typeof details.meta === "object"
                ? (details.meta as Record<string, unknown>)
                : null,
          },
        };
      }
      return {
        requestId: String(event.requestId),
        type: "question",
        phase: "asked",
        details: {
          displayMessage:
            typeof details.displayMessage === "string"
              ? details.displayMessage
              : null,
          questions: Array.isArray(details.questions)
            ? details.questions.map((question) => {
                const item = question as Record<string, unknown>;
                return {
                  header: typeof item.header === "string" ? item.header : null,
                  question: String(item.question ?? ""),
                  description:
                    typeof item.description === "string"
                      ? item.description
                      : null,
                  options: [],
                };
              })
            : [],
        },
      };
    };

    interruptLifecycleMessageCases.forEach((testCase) => {
      const update = buildInterruptEventBlockUpdate({
        messageId: `msg-${testCase.name}`,
        interrupt: toRuntimeInterrupt(testCase.event),
      });

      expect(update.delta).toBe(testCase.content);
    });
  });

  it("supports overwrite semantics when explicit replace operation arrives", () => {
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
          op: "replace",
          taskId: "task-2",
          seq: 2,
        }),
      ),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks?.[0]?.content).toBe("reset");
  });

  it("accepts explicit finalize operations without content", () => {
    let blocks: MessageBlock[] | undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          delta: "draft",
          artifactId: "task-3:stream:text",
          blockId: "block-text-main",
          laneId: "primary_text",
          op: "append",
          taskId: "task-3",
          seq: 1,
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          artifactId: "task-3:stream:text",
          blockId: "block-text-main",
          laneId: "primary_text",
          op: "finalize",
          baseSeq: 1,
          taskId: "task-3",
          seq: 2,
        }),
      ),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks?.[0]?.content).toBe("draft");
    expect(blocks?.[0]?.isFinished).toBe(true);
    expect(blocks?.[0]?.blockId).toBe("block-text-main");
  });

  it("promotes a finished tool_call block from running to success when the next block starts", () => {
    let blocks: MessageBlock[] | undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "tool_call",
          delta: '{"tool":"bash","status":"running"}',
          artifactId: "task-tools:stream:tool-1",
          blockId: "block-tool-1",
          laneId: "tool_call",
          taskId: "task-tools",
          seq: 1,
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "tool_call",
          delta: '{"tool":"grep","status":"running"}',
          artifactId: "task-tools:stream:tool-2",
          blockId: "block-tool-2",
          laneId: "tool_call",
          taskId: "task-tools",
          seq: 2,
        }),
      ),
    );

    expect(blocks).toHaveLength(2);
    expect(blocks?.[0]).toMatchObject({
      blockId: "block-tool-1",
      isFinished: true,
      toolCall: {
        name: "bash",
        status: "completed",
      },
    });
    expect(blocks?.[1]).toMatchObject({
      blockId: "block-tool-2",
      isFinished: false,
      toolCall: {
        name: "grep",
        status: "running",
      },
    });
  });

  it("promotes the last finished tool_call block from running to success during finalization", () => {
    const blocks = finalizeMessageBlocks([
      {
        id: "block-tool-last",
        blockId: "block-tool-last",
        laneId: "tool_call",
        type: "tool_call",
        content: '{"tool":"bash","status":"running"}',
        isFinished: false,
        toolCall: {
          name: "bash",
          status: "running",
          callId: null,
          arguments: undefined,
          result: undefined,
          error: undefined,
        },
        createdAt: "2026-03-26T00:00:00.000Z",
        updatedAt: "2026-03-26T00:00:00.000Z",
      },
    ]);

    expect(blocks?.[0]).toMatchObject({
      isFinished: true,
      toolCall: {
        name: "bash",
        status: "completed",
      },
    });
  });

  it("replaces inferred completed tool_call status when a later explicit success arrives", () => {
    let blocks = finalizeMessageBlocks([
      {
        id: "block-tool-late-success",
        blockId: "block-tool-late-success",
        laneId: "tool_call",
        type: "tool_call",
        content: '{"tool":"bash","status":"running"}',
        isFinished: false,
        toolCall: {
          name: "bash",
          status: "running",
          callId: null,
          arguments: undefined,
          result: undefined,
          error: undefined,
        },
        createdAt: "2026-03-26T00:00:00.000Z",
        updatedAt: "2026-03-26T00:00:00.000Z",
      },
    ]);

    expect(blocks?.[0]).toMatchObject({
      isFinished: true,
      toolCall: {
        name: "bash",
        status: "completed",
      },
    });

    blocks = applyStreamBlockUpdate(blocks, {
      eventId: "evt-tool-late-success",
      eventIdSource: "upstream",
      messageIdSource: "upstream",
      seq: 3,
      taskId: "task-tools",
      artifactId: "task-tools:stream:tool-late-success",
      blockId: "block-tool-late-success",
      laneId: "tool_call",
      blockType: "tool_call",
      op: "replace",
      baseSeq: 3,
      source: "tool_part_update",
      messageId: "msg-tool-late-success",
      role: "agent",
      delta:
        '{"call_id":"call-late-success","tool":"bash","status":"success","output":"done"}',
      append: false,
      done: true,
      toolCall: {
        name: "bash",
        status: "success",
        callId: "call-late-success",
        arguments: undefined,
        result: "done",
        error: undefined,
      },
    });

    expect(blocks?.[0]).toMatchObject({
      isFinished: true,
      toolCall: {
        name: "bash",
        status: "success",
        callId: "call-late-success",
        result: "done",
      },
    });
  });

  it("rejects stale replace operations when base_seq moves backwards", () => {
    let blocks: MessageBlock[] | undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          delta: "draft",
          artifactId: "task-4:stream:text",
          blockId: "block-text-main",
          laneId: "primary_text",
          op: "append",
          taskId: "task-4",
          seq: 1,
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          delta: "authoritative",
          artifactId: "task-4:stream:text",
          blockId: "block-text-main",
          laneId: "primary_text",
          op: "replace",
          baseSeq: 10,
          taskId: "task-4",
          seq: 11,
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          delta: "stale",
          artifactId: "task-4:stream:text",
          blockId: "block-text-main",
          laneId: "primary_text",
          op: "replace",
          baseSeq: 8,
          taskId: "task-4",
          seq: 12,
        }),
      ),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks?.[0]?.content).toBe("authoritative");
    expect(blocks?.[0]?.baseSeq).toBe(10);
  });

  it("replaces the declared primary text block without snapshot-source heuristics", () => {
    let blocks: MessageBlock[] | undefined;
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          delta: "draft",
          artifactId: "task-5:stream:text",
          blockId: "block-text-main",
          laneId: "primary_text",
          op: "append",
          taskId: "task-5",
          seq: 1,
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "reasoning",
          delta: "draft plan",
          artifactId: "task-5:stream:reasoning",
          taskId: "task-5",
          seq: 2,
          op: "replace",
        }),
      ),
    );
    blocks = applyStreamBlockUpdate(
      blocks,
      mustParse(
        buildBlockUpdatePayload({
          blockType: "text",
          delta: "final answer",
          artifactId: "task-5:stream:text:final",
          blockId: "block-text-main",
          laneId: "primary_text",
          op: "replace",
          taskId: "task-5",
          seq: 3,
          lastChunk: true,
        }),
      ),
    );

    expect(blocks).toHaveLength(2);
    expect(blocks?.[0]).toMatchObject({
      type: "text",
      blockId: "block-text-main",
      laneId: "primary_text",
      content: "final answer",
      isFinished: true,
    });
    expect(blocks?.[1]?.type).toBe("reasoning");
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

  it("parses blockType from canonical metadata", () => {
    const parsed = extractStreamBlockUpdate(
      withHubStreamBlock(
        {
          artifactUpdate: {
            taskId: "task-9",
            artifact: {
              artifactId: "task-9:stream",
              parts: [{ text: "hello" }],
            },
          },
        },
        {
          eventId: "evt-9",
          eventIdSource: "upstream",
          messageIdSource: "upstream",
          seq: 9,
          taskId: "task-9",
          artifactId: "task-9:stream",
          blockId: "msg-9:primary_text",
          laneId: "primary_text",
          blockType: "text",
          op: "append",
          baseSeq: null,
          source: null,
          messageId: "msg-9",
          role: "agent",
          delta: "hello",
          append: true,
          done: false,
        },
      ),
    );
    expect(parsed?.blockType).toBe("text");
    expect(parsed?.eventIdSource).toBe("upstream");
  });

  it("prefers standard metadata.blockType", () => {
    const parsed = extractStreamBlockUpdate(
      withHubStreamBlock(
        {
          artifactUpdate: {
            taskId: "task-9",
            artifact: {
              artifactId: "task-9:stream",
              parts: [{ text: "thinking" }],
            },
          },
        },
        {
          eventId: "evt-9",
          eventIdSource: "upstream",
          messageIdSource: "upstream",
          seq: null,
          taskId: "task-9",
          artifactId: "task-9:stream",
          blockId: "msg-9:reasoning",
          laneId: "reasoning",
          blockType: "reasoning",
          op: "append",
          baseSeq: null,
          source: null,
          messageId: "msg-9",
          role: "agent",
          delta: "thinking",
          append: true,
          done: false,
        },
      ),
    );
    expect(parsed?.blockType).toBe("reasoning");
  });

  it("prefers shared.stream metadata for tool_call blocks carried in text parts", () => {
    const parsed = extractStreamBlockUpdate(
      withHubStreamBlock(
        {
          artifactUpdate: {
            taskId: "task-10",
            artifact: {
              artifactId: "task-10:stream",
              parts: [{ text: '{"tool":"bash","status":"running"}' }],
            },
          },
        },
        {
          eventId: "evt-shared",
          eventIdSource: "upstream",
          messageIdSource: "upstream",
          seq: 10,
          taskId: "task-10",
          artifactId: "task-10:stream",
          blockId: "msg-shared:tool_call",
          laneId: "tool_call",
          blockType: "tool_call",
          op: "append",
          baseSeq: null,
          source: "tool_part_update",
          messageId: "msg-shared",
          role: "agent",
          delta: '{"tool":"bash","status":"running"}',
          append: true,
          done: false,
          toolCall: {
            name: "bash",
            status: "running",
            callId: null,
            arguments: null,
            result: null,
            error: null,
          },
        },
      ),
    );
    expect(parsed?.blockType).toBe("tool_call");
    expect(parsed?.messageId).toBe("msg-shared");
    expect(parsed?.eventId).toBe("evt-shared");
    expect(parsed?.seq).toBe(10);
    expect(parsed?.source).toBe("tool_part_update");
  });

  it("parses interrupt_event blocks carried in artifact metadata", () => {
    const parsed = extractStreamBlockUpdate(
      withHubStreamBlock(
        {
          artifactUpdate: {
            append: false,
            artifact: {
              artifactId: "artifact-interrupt-2",
              parts: [{ text: "Agent requested additional input: Proceed?" }],
            },
          },
        },
        {
          eventId: "evt-interrupt-2",
          eventIdSource: "upstream",
          messageIdSource: "upstream",
          seq: 8,
          taskId: "artifact-interrupt-2",
          artifactId: "artifact-interrupt-2",
          blockId: "msg-interrupt-2:interrupt_event",
          laneId: "interrupt_event",
          blockType: "interrupt_event",
          op: "replace",
          baseSeq: null,
          source: "interrupt_lifecycle",
          messageId: "msg-interrupt-2",
          role: "agent",
          delta: "Agent requested additional input: Proceed?",
          append: false,
          done: false,
        },
      ),
    );

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
    const parsed = extractStreamBlockUpdate(
      withHubStreamBlock(
        {
          artifactUpdate: {
            taskId: "task-10",
            artifact: {
              artifactId: "task-10:stream",
              parts: [
                {
                  data: {
                    call_id: "call-1",
                    tool: "read",
                    status: "pending",
                    input: {},
                  },
                },
              ],
            },
          },
        },
        {
          eventId: "evt-data",
          eventIdSource: "upstream",
          messageIdSource: "upstream",
          seq: 11,
          taskId: "task-10",
          artifactId: "task-10:stream",
          blockId: "msg-data:tool_call",
          laneId: "tool_call",
          blockType: "tool_call",
          op: "append",
          baseSeq: null,
          source: "tool_part_update",
          messageId: "msg-data",
          role: "agent",
          delta:
            '{"call_id":"call-1","input":{},"status":"pending","tool":"read"}',
          append: true,
          done: false,
          toolCall: {
            name: "read",
            status: "running",
            callId: "call-1",
            arguments: {},
          },
        },
      ),
    );
    expect(parsed?.blockType).toBe("tool_call");
    expect(parsed?.delta).toBe(
      '{"call_id":"call-1","input":{},"status":"pending","tool":"read"}',
    );
    expect(parsed?.messageId).toBe("msg-data");
    expect(parsed?.eventId).toBe("evt-data");
    expect(parsed?.seq).toBe(11);
    expect(parsed?.toolCall).toEqual({
      name: "read",
      status: "running",
      callId: "call-1",
      arguments: {},
      result: undefined,
      error: undefined,
    });
  });

  it("infers text block type for canonical message wrappers", () => {
    const parsed = extractStreamBlockUpdate(
      withHubStreamBlock(
        {
          message: {
            role: "ROLE_AGENT",
            parts: [{ text: "hello" }],
          },
        },
        {
          eventId: "evt-message-9",
          eventIdSource: "upstream",
          messageIdSource: "upstream",
          seq: null,
          taskId: "msg-message-9",
          artifactId: "msg-message-9:text",
          blockId: "msg-message-9:primary_text",
          laneId: "primary_text",
          blockType: "text",
          op: "replace",
          baseSeq: null,
          source: null,
          messageId: "msg-message-9",
          role: "agent",
          delta: "hello",
          append: false,
          done: false,
        },
      ),
    );
    expect(parsed?.blockType).toBe("text");
    expect(parsed?.messageId).toBe("msg-message-9");
  });

  it("infers text block type for status-update message wrappers", () => {
    const parsed = extractStreamBlockUpdate(
      withHubStreamBlock(
        {
          statusUpdate: {
            status: {
              state: "TASK_STATE_WORKING",
              message: {
                messageId: "msg-status-9",
                taskId: "task-status-9",
                role: "ROLE_AGENT",
                parts: [{ text: "hello from status message" }],
              },
            },
          },
        },
        {
          eventId: "evt-status-9",
          eventIdSource: "upstream",
          messageIdSource: "upstream",
          seq: null,
          taskId: "task-status-9",
          artifactId: "msg-status-9:text",
          blockId: "msg-status-9:primary_text",
          laneId: "primary_text",
          blockType: "text",
          op: "replace",
          baseSeq: null,
          source: null,
          messageId: "msg-status-9",
          role: "agent",
          delta: "hello from status message",
          append: false,
          done: false,
        },
      ),
    );
    expect(parsed?.blockType).toBe("text");
    expect(parsed?.messageId).toBe("msg-status-9");
    expect(parsed?.taskId).toBe("task-status-9");
    expect(parsed?.eventId).toBe("evt-status-9");
    expect(parsed?.delta).toBe("hello from status message");
  });

  it("parses chunk when taskId is missing but messageId exists", () => {
    const parsed = extractStreamBlockUpdate(
      withHubStreamBlock(
        {
          artifactUpdate: {
            artifact: {
              artifactId: "stream-1",
              parts: [{ text: "hello" }],
            },
          },
        },
        {
          eventId: "chunk:msg-only-1:stream-1",
          eventIdSource: "fallback_chunk",
          messageIdSource: "upstream",
          seq: null,
          taskId: "msg-only-1",
          artifactId: "stream-1",
          blockId: "msg-only-1:primary_text",
          laneId: "primary_text",
          blockType: "text",
          op: "append",
          baseSeq: null,
          source: null,
          messageId: "msg-only-1",
          role: "agent",
          delta: "hello",
          append: true,
          done: false,
        },
      ),
    );
    expect(parsed?.messageId).toBe("msg-only-1");
    expect(parsed?.taskId).toBe("msg-only-1");
  });

  it("ignores unsupported blockType values", () => {
    const parsed = extractStreamBlockUpdate(
      withHubStreamBlock(
        {
          artifactUpdate: {
            taskId: "task-8",
            artifact: {
              artifactId: "task-8:stream",
              parts: [{ text: "noop" }],
            },
          },
        },
        {
          eventId: "evt-8",
          eventIdSource: "upstream",
          messageIdSource: "upstream",
          seq: 8,
          taskId: "task-8",
          artifactId: "task-8:stream",
          blockId: "msg-8:custom_phase",
          laneId: "custom_phase",
          blockType: "custom_phase",
          op: "append",
          baseSeq: null,
          source: null,
          messageId: "msg-8",
          role: "agent",
          delta: "noop",
          append: true,
          done: false,
        },
      ),
    );
    expect(parsed).toBeNull();
  });

  it("falls back to task-based message id when messageId is missing", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
      messageId: "",
    }) as Record<string, unknown>;
    delete (
      payload.artifactUpdate as {
        artifact?: {
          metadata?: { shared?: { stream?: Record<string, unknown> } };
        };
      }
    ).artifact?.metadata?.shared?.stream?.messageId;
    (
      ((payload as { streamBlock?: Record<string, unknown> }).streamBlock ??
        {}) as Record<string, unknown>
    ).messageId = "task:task-1";
    (
      ((payload as { streamBlock?: Record<string, unknown> }).streamBlock ??
        {}) as Record<string, unknown>
    ).messageIdSource = "task_fallback";
    const parsed = extractStreamBlockUpdate(payload);
    expect(parsed?.messageId).toBe("task:task-1");
    expect(parsed?.messageIdSource).toBe("task_fallback");
  });

  it("accepts raw A2A artifact text chunks without custom block metadata", () => {
    const payload = withHubStreamBlock(
      {
        artifactUpdate: {
          taskId: "task-raw-1",
          contextId: "ctx-raw-1",
          append: true,
          lastChunk: false,
          artifact: {
            artifactId: "task-raw-1:stream:text",
            parts: [{ text: "Code" }],
          },
          metadata: {
            shared: {
              stream: {
                seq: 4,
                eventId: "stream:4",
              },
            },
          },
        },
      },
      {
        eventId: "stream:4",
        eventIdSource: "upstream",
        messageIdSource: "task_fallback",
        seq: 4,
        taskId: "task-raw-1",
        artifactId: "task-raw-1:stream:text",
        blockId: "task:task-raw-1:primary_text",
        laneId: "primary_text",
        blockType: "text",
        op: "append",
        baseSeq: null,
        source: null,
        messageId: "task:task-raw-1",
        role: "agent",
        delta: "Code",
        append: true,
        done: false,
      },
    );

    const parsed = extractStreamBlockUpdate(payload);

    expect(parsed).not.toBeNull();
    expect(parsed?.blockType).toBe("text");
    expect(parsed?.op).toBe("append");
    expect(parsed?.delta).toBe("Code");
    expect(parsed?.messageId).toBe("task:task-raw-1");
    expect(parsed?.messageIdSource).toBe("task_fallback");
    expect(parsed?.eventId).toBe("stream:4");
  });

  it("uses seq-based fallback when eventId is missing", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
      seq: 7,
    }) as Record<string, unknown>;
    delete (
      payload.artifactUpdate as {
        artifact?: {
          metadata?: { shared?: { stream?: Record<string, unknown> } };
        };
      }
    ).artifact?.metadata?.shared?.stream?.eventId;
    (
      ((payload as { streamBlock?: Record<string, unknown> }).streamBlock ??
        {}) as Record<string, unknown>
    ).eventId = "seq:msg-1:7";
    (
      ((payload as { streamBlock?: Record<string, unknown> }).streamBlock ??
        {}) as Record<string, unknown>
    ).eventIdSource = "fallback_seq";
    const parsed = extractStreamBlockUpdate(payload);
    expect(parsed?.eventId).toBe("seq:msg-1:7");
    expect(parsed?.eventIdSource).toBe("fallback_seq");
  });

  it("accepts local persistence identity sources from canonical stream blocks", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
    }) as Record<string, unknown>;
    (
      ((payload as { streamBlock?: Record<string, unknown> }).streamBlock ??
        {}) as Record<string, unknown>
    ).messageIdSource = "local_persistence";
    (
      ((payload as { streamBlock?: Record<string, unknown> }).streamBlock ??
        {}) as Record<string, unknown>
    ).eventIdSource = "local_persistence";

    const parsed = extractStreamBlockUpdate(payload);

    expect(parsed?.messageIdSource).toBe("local_persistence");
    expect(parsed?.eventIdSource).toBe("local_persistence");
  });

  it("accepts chunks using camelCase message/event fields", () => {
    const payload = withHubStreamBlock(
      {
        artifactUpdate: {
          taskId: "task-1",
          artifact: {
            artifactId: "task-1:stream",
            parts: [{ text: "hello" }],
          },
        },
      },
      {
        eventId: "evt-camel",
        eventIdSource: "upstream",
        messageIdSource: "upstream",
        seq: null,
        taskId: "task-1",
        artifactId: "task-1:stream",
        blockId: "msg-camel:primary_text",
        laneId: "primary_text",
        blockType: "text",
        op: "append",
        baseSeq: null,
        source: null,
        messageId: "msg-camel",
        role: "agent",
        delta: "hello",
        append: true,
        done: false,
      },
    );
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

  it("uses chunk-based fallback when both seq and eventId are missing", () => {
    const payload = buildBlockUpdatePayload({
      blockType: "text",
      delta: "hello",
      artifactId: "task-1:stream",
      seq: undefined,
    }) as Record<string, unknown>;
    delete (
      payload.artifactUpdate as {
        artifact?: {
          metadata?: { shared?: { stream?: Record<string, unknown> } };
        };
      }
    ).artifact?.metadata?.shared?.stream?.eventId;
    (
      ((payload as { streamBlock?: Record<string, unknown> }).streamBlock ??
        {}) as Record<string, unknown>
    ).eventId = "chunk:msg-1:task-1:stream";
    (
      ((payload as { streamBlock?: Record<string, unknown> }).streamBlock ??
        {}) as Record<string, unknown>
    ).eventIdSource = "fallback_chunk";
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
    const payload = buildStatusUpdatePayload({
      state: "TASK_STATE_INPUT_REQUIRED",
    });

    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "input-required",
      isFinal: true,
      interrupt: null,
      seq: null,
      completionPhase: null,
      messageId: null,
    });
  });

  it("returns null runtime status event for non-status payload", () => {
    expect(extractRuntimeStatusEvent({ artifactUpdate: {} })).toBeNull();
  });

  it("parses status-update seq for resume tracking", () => {
    const payload = buildStatusUpdatePayload({
      state: "TASK_STATE_WORKING",
      seq: 4,
    });

    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "working",
      isFinal: false,
      interrupt: null,
      seq: 4,
      completionPhase: null,
      messageId: null,
    });
  });

  it("parses permission interrupt metadata from status-update", () => {
    const payload = buildStatusUpdatePayload({
      state: "TASK_STATE_INPUT_REQUIRED",
      interrupt: {
        requestId: "perm-1",
        type: "permission",
        details: {
          permission: "read",
          patterns: ["/repo/.env"],
        },
      },
    });
    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "input-required",
      isFinal: true,
      interrupt: {
        requestId: "perm-1",
        type: "permission",
        phase: "asked",
        source: "stream",
        details: {
          permission: "read",
          patterns: ["/repo/.env"],
          displayMessage: null,
        },
      },
      seq: null,
      completionPhase: null,
      messageId: null,
    });
  });

  it("parses richer permission interrupt display text from nested metadata", () => {
    const payload = buildStatusUpdatePayload({
      state: "TASK_STATE_INPUT_REQUIRED",
      interrupt: {
        requestId: "perm-2",
        type: "permission",
        details: {
          permission: "approval",
          patterns: ["/repo/.env"],
          request: {
            description: "Agent wants to read the environment file.",
          },
        },
      },
    });
    expect(extractRuntimeStatusEvent(payload)?.interrupt).toEqual({
      requestId: "perm-2",
      type: "permission",
      phase: "asked",
      source: "stream",
      details: {
        permission: "approval",
        patterns: ["/repo/.env"],
        displayMessage: "Agent wants to read the environment file.",
      },
    });
  });

  it("parses question interrupt metadata from status-update", () => {
    const payload = buildStatusUpdatePayload({
      state: "TASK_STATE_INPUT_REQUIRED",
      interrupt: {
        requestId: "q-1",
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
    });
    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "input-required",
      isFinal: true,
      interrupt: {
        requestId: "q-1",
        type: "question",
        phase: "asked",
        source: "stream",
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
      seq: null,
      completionPhase: null,
      messageId: null,
    });
  });

  it("parses richer question interrupt metadata from nested fields", () => {
    const payload = buildStatusUpdatePayload({
      state: "TASK_STATE_INPUT_REQUIRED",
      interrupt: {
        requestId: "q-2",
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
    });
    expect(extractRuntimeStatusEvent(payload)?.interrupt).toEqual({
      requestId: "q-2",
      type: "question",
      phase: "asked",
      source: "stream",
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
    const payload = buildStatusUpdatePayload({
      state: "TASK_STATE_WORKING",
      interrupt: {
        requestId: "q-1",
        type: "question",
        phase: "resolved",
        resolution: "rejected",
      },
    });
    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "working",
      isFinal: false,
      interrupt: {
        requestId: "q-1",
        type: "question",
        phase: "resolved",
        source: "stream",
        resolution: "rejected",
      },
      seq: null,
      completionPhase: null,
      messageId: null,
    });
  });

  it("parses explicit persisted completion acknowledgement from shared stream metadata", () => {
    const payload = buildStatusUpdatePayload({
      state: "TASK_STATE_COMPLETED",
      messageId: "msg-persisted-1",
      completionPhase: "persisted",
    });

    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "completed",
      isFinal: true,
      interrupt: null,
      seq: null,
      completionPhase: "persisted",
      messageId: "msg-persisted-1",
    });
  });

  it("ignores unrelated persisted alias flags when canonical stream metadata is present", () => {
    const payload = buildStatusUpdatePayload({
      state: "TASK_STATE_COMPLETED",
      messageId: "msg-persisted-2",
      completionPhase: "persisted",
    }) as Record<string, unknown>;
    (
      ((
        payload.statusUpdate as {
          metadata?: { shared?: { stream?: Record<string, unknown> } };
        }
      ).metadata?.shared?.stream ?? {}) as Record<string, unknown>
    ).persisted = true;

    expect(extractRuntimeStatusEvent(payload)).toEqual({
      state: "completed",
      isFinal: true,
      interrupt: null,
      seq: null,
      completionPhase: "persisted",
      messageId: "msg-persisted-2",
    });
  });

  it("extracts external session from canonical shared session metadata", () => {
    const meta = extractSessionMeta({
      version: "v1",
      sessionMeta: {
        provider: "opencode",
        externalSessionId: "ses_upstream_1",
      },
    });
    expect(meta.provider).toBe("opencode");
    expect(meta.externalSessionId).toBe("ses_upstream_1");
  });

  it("requires shared interrupt metadata on canonical status-update payloads", () => {
    const payload = {
      version: "v1",
      runtimeStatus: {
        state: "input-required",
        isFinal: true,
        interrupt: null,
      },
    };
    expect(extractRuntimeStatusEvent(payload)?.interrupt).toBeNull();
  });
});
