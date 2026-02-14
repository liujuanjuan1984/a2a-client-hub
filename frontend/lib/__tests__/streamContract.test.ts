import {
  applyStreamArtifactUpdate,
  extractStreamArtifactUpdate,
  projectStreamChannelContent,
  type StreamArtifactRecord,
  type StreamArtifactUpdate,
} from "@/lib/api/chat-utils";

const buildArtifactUpdatePayload = (input: {
  channel: "reasoning" | "tool_call" | "final_answer";
  text: string;
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
    parts: [{ kind: "text", text: input.text }],
    metadata: {
      opencode: {
        channel: input.channel,
        source: input.source ?? "stream",
      },
    },
  },
});

const mustParse = (payload: Record<string, unknown>): StreamArtifactUpdate => {
  const parsed = extractStreamArtifactUpdate(payload);
  expect(parsed).not.toBeNull();
  return parsed as StreamArtifactUpdate;
};

describe("opencode stream contract parser and state machine", () => {
  it("renders reasoning/tool_call/final_answer independently", () => {
    let artifacts: Record<string, StreamArtifactRecord> | undefined = undefined;
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "reasoning",
          text: "thinking...",
          artifactId: "task-1:stream:reasoning",
        }),
      ),
    );
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "tool_call",
          text: "search(query='weather')",
          artifactId: "task-1:stream:tool_call",
        }),
      ),
    );
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "final_answer",
          text: "It is sunny.",
          artifactId: "task-1:stream",
        }),
      ),
    );

    const projected = projectStreamChannelContent(artifacts);
    expect(projected.finalAnswer).toBe("It is sunny.");
    expect(projected.reasoning).toBe("thinking...");
    expect(projected.toolCall).toBe("search(query='weather')");
  });

  it("treats final_snapshot as overwrite for final_answer", () => {
    let artifacts: Record<string, StreamArtifactRecord> | undefined = undefined;
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "final_answer",
          text: "Hello ",
          artifactId: "task-1:stream",
          append: true,
        }),
      ),
    );
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "final_answer",
          text: "world",
          artifactId: "task-1:stream",
          append: true,
        }),
      ),
    );
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "final_answer",
          text: "Hello world",
          artifactId: "task-1:stream",
          append: false,
          source: "final_snapshot",
          lastChunk: true,
        }),
      ),
    );

    const projected = projectStreamChannelContent(artifacts);
    expect(projected.finalAnswer).toBe("Hello world");
    expect(Object.keys(artifacts ?? {})).toHaveLength(1);
  });

  it("keeps buffers isolated across artifact ids", () => {
    let artifacts: Record<string, StreamArtifactRecord> | undefined = undefined;
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "reasoning",
          text: "plan A",
          artifactId: "task-1:stream:reasoning",
          append: false,
        }),
      ),
    );
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "final_answer",
          text: "answer A",
          artifactId: "task-1:stream",
        }),
      ),
    );
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "reasoning",
          text: " + detail",
          artifactId: "task-1:stream:reasoning",
          append: true,
        }),
      ),
    );

    const projected = projectStreamChannelContent(artifacts);
    expect(projected.reasoning).toBe("plan A + detail");
    expect(projected.finalAnswer).toBe("answer A");
  });

  it("applies append=false as overwrite and append=true as subsequent append", () => {
    let artifacts: Record<string, StreamArtifactRecord> | undefined = undefined;
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "final_answer",
          text: "first",
          artifactId: "task-2:stream",
          append: true,
          taskId: "task-2",
        }),
      ),
    );
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "final_answer",
          text: "reset",
          artifactId: "task-2:stream",
          append: false,
          taskId: "task-2",
        }),
      ),
    );
    artifacts = applyStreamArtifactUpdate(
      artifacts,
      mustParse(
        buildArtifactUpdatePayload({
          channel: "final_answer",
          text: "!",
          artifactId: "task-2:stream",
          append: true,
          taskId: "task-2",
        }),
      ),
    );

    const projected = projectStreamChannelContent(artifacts);
    expect(projected.finalAnswer).toBe("reset!");
  });

  it("ignores chunks without message_id", () => {
    const payload = buildArtifactUpdatePayload({
      channel: "final_answer",
      text: "hello",
      artifactId: "task-1:stream",
      messageId: "",
    }) as Record<string, unknown>;
    delete payload.message_id;
    const parsed = extractStreamArtifactUpdate(payload);
    expect(parsed).toBeNull();
  });
});
