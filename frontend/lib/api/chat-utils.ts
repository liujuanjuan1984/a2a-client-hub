export type ChatRole = "user" | "agent" | "system";

export type MessageBlock = {
  id: string;
  type: string;
  content: string;
  isFinished: boolean;
  createdAt: string;
  updatedAt: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  status?: "streaming" | "done";
  blocks?: MessageBlock[];
};

export type StreamBlockUpdate = {
  taskId: string;
  artifactId: string;
  contentType: string;
  source: string | null;
  messageId: string;
  role: ChatRole;
  delta: string;
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

const pickRawString = (
  source: Record<string, unknown> | null,
  keys: string[],
): string | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string") {
      return value;
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

const parseContentType = (raw: string | null): string | null => {
  const normalized = (raw ?? "").trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "final_answer") return "text";
  return normalized;
};

const inferTaskIdFromArtifactId = (
  artifactId: string | null,
): string | null => {
  if (!artifactId) return null;
  const firstSep = artifactId.indexOf(":");
  if (firstSep <= 0) return null;
  return artifactId.slice(0, firstSep);
};

export const extractStreamBlockUpdate = (
  data: Record<string, unknown>,
): StreamBlockUpdate | null => {
  const kind = pickString(data, ["kind"]);
  if (kind && kind !== "artifact-update") {
    return null;
  }
  const artifact = asRecord(data.artifact);
  const metadata = asRecord(artifact?.metadata);
  const opencodeMetadata = asRecord(metadata?.opencode);
  const contentType = parseContentType(
    pickString(opencodeMetadata, ["content_type", "contentType"]) ??
      pickString(artifact ?? null, ["content_type", "contentType"]) ??
      pickString(data, ["content_type", "contentType"]) ??
      pickString(opencodeMetadata, ["channel", "stream_channel"]),
  );
  if (!contentType) {
    return null;
  }

  const messageId =
    pickString(data, ["message_id", "messageId"]) ??
    pickString(artifact ?? null, ["message_id", "messageId"]) ??
    pickString(opencodeMetadata, ["message_id", "messageId"]);
  // New contract: missing message_id events are invalid and should be ignored.
  if (!messageId) {
    return null;
  }

  const artifactId =
    pickString(artifact ?? null, ["artifact_id", "artifactId", "id"]) ??
    `${messageId}:${contentType}`;
  if (!artifactId) {
    return null;
  }
  const taskId =
    pickString(data, ["task_id", "taskId"]) ??
    pickString(artifact ?? null, ["task_id", "taskId"]) ??
    inferTaskIdFromArtifactId(artifactId);
  if (!taskId) {
    return null;
  }

  const parts = Array.isArray(artifact?.parts) ? artifact.parts : [];
  const delta =
    extractTextFromParts(parts) ||
    pickRawString(data, ["delta"]) ||
    pickRawString(artifact ?? null, ["delta"]) ||
    pickRawString(data, ["content", "text"]) ||
    pickRawString(artifact ?? null, ["content", "text"]) ||
    "";
  if (!delta) {
    return null;
  }

  const append =
    typeof data.append === "boolean"
      ? data.append
      : typeof artifact?.append === "boolean"
        ? artifact.append
        : true;
  const done =
    data.lastChunk === true ||
    data.last_chunk === true ||
    artifact?.lastChunk === true ||
    artifact?.last_chunk === true;

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
    contentType,
    source,
    messageId,
    role,
    delta,
    append,
    done,
  };
};

export const applyStreamBlockUpdate = (
  current: MessageBlock[] | undefined,
  update: StreamBlockUpdate,
) => {
  const blocks = [...(current ?? [])];
  const now = new Date().toISOString();
  const overwrite = update.source === "final_snapshot" || !update.append;
  const lastBlock = blocks[blocks.length - 1];

  if (overwrite) {
    if (
      lastBlock &&
      lastBlock.type === update.contentType &&
      lastBlock.isFinished === false
    ) {
      lastBlock.content = update.delta;
      lastBlock.isFinished = update.done;
      lastBlock.updatedAt = now;
      return blocks;
    }
    if (lastBlock && lastBlock.isFinished === false) {
      lastBlock.isFinished = true;
      lastBlock.updatedAt = now;
    }
    blocks.push({
      id: `${update.messageId}:${blocks.length + 1}`,
      type: update.contentType,
      content: update.delta,
      isFinished: update.done,
      createdAt: now,
      updatedAt: now,
    });
    return blocks;
  }

  if (
    lastBlock &&
    lastBlock.type === update.contentType &&
    lastBlock.isFinished === false
  ) {
    lastBlock.content = `${lastBlock.content}${update.delta}`;
    lastBlock.isFinished = update.done;
    lastBlock.updatedAt = now;
    return blocks;
  }

  if (lastBlock && lastBlock.isFinished === false) {
    lastBlock.isFinished = true;
    lastBlock.updatedAt = now;
  }

  blocks.push({
    id: `${update.messageId}:${blocks.length + 1}`,
    type: update.contentType,
    content: update.delta,
    isFinished: update.done,
    createdAt: now,
    updatedAt: now,
  });
  return blocks;
};

export const projectPrimaryTextContent = (
  blocks: MessageBlock[] | undefined,
): string =>
  (blocks ?? [])
    .filter((block) => block.type === "text")
    .map((block) => block.content)
    .join("");
