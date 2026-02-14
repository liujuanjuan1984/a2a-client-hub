export type ChatRole = "user" | "agent" | "system";

export type StreamChannel = "reasoning" | "tool_call" | "final_answer";

export type StreamArtifactRecord = {
  taskId: string;
  artifactId: string;
  channel: StreamChannel;
  source: string | null;
  messageId: string;
  role: ChatRole;
  content: string;
  append: boolean;
  done: boolean;
  updatedAt: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  status?: "streaming" | "done";
  streamArtifacts?: Record<string, StreamArtifactRecord>;
  reasoningContent?: string;
  toolCallContent?: string;
};

export type StreamArtifactUpdate = {
  taskId: string;
  artifactId: string;
  channel: StreamChannel;
  source: string | null;
  messageId: string;
  role: ChatRole;
  text: string;
  append: boolean;
  done: boolean;
};

const coerceStringArray = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "string")
    ? (value as string[])
    : undefined;

export const extractSessionMeta = (data: Record<string, unknown>) => {
  const contextId =
    typeof data.context_id === "string"
      ? data.context_id
      : typeof data.contextId === "string"
        ? data.contextId
        : null;
  const transport =
    typeof data.transport === "string" ? data.transport : undefined;
  const inputModes =
    coerceStringArray(data.input_modes) ?? coerceStringArray(data.inputModes);
  const outputModes =
    coerceStringArray(data.output_modes) ?? coerceStringArray(data.outputModes);

  return {
    contextId,
    transport,
    inputModes,
    outputModes,
  };
};

export const extractRuntimeStatus = (data: Record<string, unknown>) => {
  if (data.kind !== "status-update") {
    return null;
  }
  const status = data.status as { state?: unknown } | undefined;
  if (status && typeof status.state === "string") {
    return status.state;
  }
  return null;
};

const extractTextFromParts = (parts: unknown[]) =>
  parts
    .map((part) => {
      if (!part || typeof part !== "object") {
        return null;
      }
      const typed = part as { kind?: unknown; text?: unknown };
      if (typed.kind === "text" && typeof typed.text === "string") {
        return typed.text;
      }
      return null;
    })
    .filter((item): item is string => Boolean(item))
    .join("");

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const pickString = (
  source: Record<string, unknown> | null,
  keys: string[],
): string | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
};

const normalizeRole = (raw: string | null): ChatRole => {
  const role = (raw ?? "").trim().toLowerCase();
  if (role === "user" || role === "human" || role === "automation") {
    return "user";
  }
  if (role === "assistant" || role === "agent") {
    return "agent";
  }
  return "system";
};

const parseStreamChannel = (raw: string | null): StreamChannel | null => {
  if (raw === "reasoning" || raw === "tool_call" || raw === "final_answer") {
    return raw;
  }
  return null;
};

const inferTaskIdFromArtifactId = (
  artifactId: string | null,
): string | null => {
  if (!artifactId) return null;
  const firstSep = artifactId.indexOf(":");
  if (firstSep <= 0) return null;
  return artifactId.slice(0, firstSep);
};

export const buildStreamArtifactKey = (taskId: string, artifactId: string) =>
  `${taskId}::${artifactId}`;

export const extractStreamArtifactUpdate = (
  data: Record<string, unknown>,
): StreamArtifactUpdate | null => {
  if (data.kind !== "artifact-update") {
    return null;
  }
  const artifact = asRecord(data.artifact);
  if (!artifact) {
    return null;
  }
  const metadata = asRecord(artifact.metadata);
  const opencodeMetadata = asRecord(metadata?.opencode);
  const channel = parseStreamChannel(
    pickString(opencodeMetadata, ["channel", "stream_channel"]),
  );
  if (!channel) {
    return null;
  }

  const artifactId = pickString(artifact, ["artifact_id", "artifactId", "id"]);
  if (!artifactId) {
    return null;
  }
  const taskId =
    pickString(data, ["task_id", "taskId"]) ??
    pickString(artifact, ["task_id", "taskId"]) ??
    inferTaskIdFromArtifactId(artifactId);
  if (!taskId) {
    return null;
  }

  const messageId =
    pickString(data, ["message_id", "messageId"]) ??
    pickString(artifact, ["message_id", "messageId"]) ??
    pickString(opencodeMetadata, ["message_id", "messageId"]);
  // New contract: missing message_id events are invalid and should be ignored.
  if (!messageId) {
    return null;
  }

  const parts = Array.isArray(artifact.parts) ? artifact.parts : [];
  const text = extractTextFromParts(parts);
  if (!text) {
    return null;
  }

  const append =
    typeof data.append === "boolean"
      ? data.append
      : typeof artifact.append === "boolean"
        ? artifact.append
        : true;
  const done =
    data.lastChunk === true ||
    data.last_chunk === true ||
    artifact.lastChunk === true ||
    artifact.last_chunk === true;

  const source =
    pickString(opencodeMetadata, ["source"]) ??
    pickString(metadata, ["source"]) ??
    null;
  const role = normalizeRole(
    pickString(data, ["role"]) ?? pickString(opencodeMetadata, ["role"]),
  );

  return {
    taskId,
    artifactId,
    channel,
    source,
    messageId,
    role,
    text,
    append,
    done,
  };
};

export const applyStreamArtifactUpdate = (
  current: Record<string, StreamArtifactRecord> | undefined,
  update: StreamArtifactUpdate,
) => {
  const artifacts = current ?? {};
  const key = buildStreamArtifactKey(update.taskId, update.artifactId);
  const previous = artifacts[key];
  const overwrite = update.source === "final_snapshot" || !update.append;
  const nextContent = overwrite
    ? update.text
    : `${previous?.content ?? ""}${update.text}`;

  return {
    ...artifacts,
    [key]: {
      taskId: update.taskId,
      artifactId: update.artifactId,
      channel: update.channel,
      source: update.source,
      messageId: update.messageId,
      role: update.role,
      content: nextContent,
      append: update.append,
      done: update.done,
      updatedAt: new Date().toISOString(),
    },
  };
};

const compareByUpdatedAt = (
  left: StreamArtifactRecord,
  right: StreamArtifactRecord,
) => left.updatedAt.localeCompare(right.updatedAt);

export const projectStreamChannelContent = (
  artifacts: Record<string, StreamArtifactRecord> | undefined,
) => {
  const entries = Object.values(artifacts ?? {});
  if (entries.length === 0) {
    return {
      finalAnswer: "",
      reasoning: "",
      toolCall: "",
    };
  }

  const reasoningItems = entries
    .filter((item) => item.channel === "reasoning")
    .sort(compareByUpdatedAt);
  const toolCallItems = entries
    .filter((item) => item.channel === "tool_call")
    .sort(compareByUpdatedAt);
  const finalAnswerItems = entries
    .filter((item) => item.channel === "final_answer")
    .sort(compareByUpdatedAt);
  const latestFinalAnswer =
    finalAnswerItems.length > 0
      ? finalAnswerItems[finalAnswerItems.length - 1]
      : null;

  return {
    finalAnswer: latestFinalAnswer?.content ?? "",
    reasoning: reasoningItems.map((item) => item.content).join("\n\n"),
    toolCall: toolCallItems.map((item) => item.content).join("\n\n"),
  };
};
