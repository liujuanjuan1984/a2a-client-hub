import {
  getPreferredInterruptMetadata,
  getPreferredSessionMetadata,
  mergeSharedMetadataSection,
} from "@/lib/sharedMetadata";

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
  status?: "streaming" | "done" | "error" | "interrupted";
  blocks?: MessageBlock[];
  errorCode?: string | null;
  errorMessage?: string | null;
};

export type StreamBlockUpdate = {
  eventId: string;
  eventIdSource: "upstream" | "fallback_seq" | "fallback_chunk";
  seq: number | null;
  taskId: string;
  artifactId: string;
  blockType: "text" | "reasoning" | "tool_call";
  source: string | null;
  messageId: string;
  role: ChatRole;
  delta: string;
  append: boolean;
  done: boolean;
};

export type RuntimeStatusEvent = {
  state: string;
  isFinal: boolean;
  interrupt: RuntimeInterrupt | null;
};

const coerceStringArray = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "string")
    ? (value as string[])
    : undefined;

export type InterruptQuestionOption = {
  label: string;
  description: string | null;
  value: string | null;
};

export type InterruptQuestion = {
  header: string | null;
  question: string;
  options: InterruptQuestionOption[];
};

type RuntimeInterruptBase = {
  requestId: string;
  type: "permission" | "question";
};

export type PendingRuntimeInterrupt = RuntimeInterruptBase & {
  phase: "asked";
  details: {
    permission?: string | null;
    patterns?: string[];
    questions?: InterruptQuestion[];
  };
};

export type ResolvedRuntimeInterrupt = RuntimeInterruptBase & {
  phase: "resolved";
  resolution: "replied" | "rejected";
};

export type RuntimeInterrupt =
  | PendingRuntimeInterrupt
  | ResolvedRuntimeInterrupt;

export const extractSessionMeta = (data: Record<string, unknown>) => {
  const contextId =
    typeof data.context_id === "string"
      ? data.context_id
      : typeof data.contextId === "string"
        ? data.contextId
        : null;
  const session = getPreferredSessionMetadata(data);
  const externalSessionId =
    pickString(session, ["id", "externalSessionId"]) ?? undefined;
  const rawProvider = pickString(session, ["provider"]);
  const provider = rawProvider?.trim().toLowerCase() ?? undefined;
  const transport =
    typeof data.transport === "string" ? data.transport : undefined;
  const inputModes =
    coerceStringArray(data.input_modes) ?? coerceStringArray(data.inputModes);
  const outputModes =
    coerceStringArray(data.output_modes) ?? coerceStringArray(data.outputModes);

  return {
    contextId,
    provider,
    externalSessionId,
    transport,
    inputModes,
    outputModes,
  };
};

export const extractRuntimeStatus = (data: Record<string, unknown>) => {
  const statusEvent = extractRuntimeStatusEvent(data);
  return statusEvent?.state ?? null;
};

export const extractRuntimeStatusEvent = (
  data: Record<string, unknown>,
): RuntimeStatusEvent | null => {
  if (data.kind !== "status-update") {
    return null;
  }
  const status = data.status as { state?: unknown } | undefined;
  if (status && typeof status.state === "string" && status.state.trim()) {
    const state = status.state;
    return {
      state,
      isFinal: data.final === true,
      interrupt: extractRuntimeInterrupt(data, state),
    };
  }
  return null;
};

const extractTextFromParts = (parts: unknown[]) =>
  parts
    .map((part) => {
      if (!part || typeof part !== "object") {
        return null;
      }
      const typed = part as {
        kind?: unknown;
        type?: unknown;
        text?: unknown;
        content?: unknown;
      };
      const rawKind = typed.kind ?? typed.type;
      const normalizedKind =
        typeof rawKind === "string" ? rawKind.trim().toLowerCase() : null;
      if (normalizedKind && normalizedKind !== "text") {
        return null;
      }
      if (typeof typed.text === "string") {
        return typed.text;
      }
      if (typeof typed.content === "string") {
        return typed.content;
      }
      return null;
    })
    .filter((item): item is string => Boolean(item))
    .join("");

const sortSerializableValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => sortSerializableValue(item));
  }
  if (value && typeof value === "object") {
    return Object.keys(value as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((acc, key) => {
        acc[key] = sortSerializableValue(
          (value as Record<string, unknown>)[key],
        );
        return acc;
      }, {});
  }
  return value;
};

const serializeDataPartValue = (value: unknown): string | null => {
  if (value === undefined || value === null) {
    return null;
  }
  try {
    return JSON.stringify(sortSerializableValue(value));
  } catch {
    return JSON.stringify(String(value));
  }
};

const extractDataFromParts = (parts: unknown[]) =>
  parts
    .map((part) => {
      if (!part || typeof part !== "object") {
        return null;
      }
      const typed = part as {
        kind?: unknown;
        type?: unknown;
        data?: unknown;
      };
      const rawKind = typed.kind ?? typed.type;
      const normalizedKind =
        typeof rawKind === "string" ? rawKind.trim().toLowerCase() : null;
      if (normalizedKind !== "data" && !("data" in typed)) {
        return null;
      }
      return serializeDataPartValue(typed.data);
    })
    .filter((item): item is string => Boolean(item))
    .join("\n");

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

const pickInteger = (
  source: Record<string, unknown> | null,
  keys: string[],
): number | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (
      typeof value === "number" &&
      Number.isFinite(value) &&
      Number.isInteger(value)
    ) {
      return value;
    }
    if (typeof value === "string" && /^-?\d+$/.test(value.trim())) {
      return Number(value.trim());
    }
  }
  return null;
};

const normalizeRuntimeState = (state: string) => state.trim().toLowerCase();

export const isInputRequiredRuntimeState = (state: string) => {
  const normalized = normalizeRuntimeState(state);
  return normalized === "input-required" || normalized === "input_required";
};

const parseInterruptQuestionOption = (
  value: unknown,
): InterruptQuestionOption | null => {
  const option = asRecord(value);
  if (!option) {
    return null;
  }
  const label = pickString(option, ["label"]);
  if (!label) {
    return null;
  }
  return {
    label,
    description: pickRawString(option, ["description"]) ?? null,
    value: pickRawString(option, ["value"]) ?? null,
  };
};

const parseInterruptQuestion = (value: unknown): InterruptQuestion | null => {
  const question = asRecord(value);
  if (!question) {
    return null;
  }
  const prompt = pickString(question, ["question"]);
  if (!prompt) {
    return null;
  }
  const rawOptions = Array.isArray(question.options) ? question.options : [];
  const options = rawOptions
    .map(parseInterruptQuestionOption)
    .filter((item): item is InterruptQuestionOption => Boolean(item));
  return {
    header: pickRawString(question, ["header"]) ?? null,
    question: prompt,
    options,
  };
};

const extractRuntimeInterrupt = (
  data: Record<string, unknown>,
  runtimeState: string,
): RuntimeInterrupt | null => {
  const interrupt = getPreferredInterruptMetadata(data);
  if (!interrupt) {
    return null;
  }
  const requestId = pickString(interrupt, ["request_id", "requestId"]);
  const interruptType = pickString(interrupt, ["type"])?.toLowerCase();
  if (
    !requestId ||
    (interruptType !== "permission" && interruptType !== "question")
  ) {
    return null;
  }

  const phase =
    pickString(interrupt, ["phase"])?.toLowerCase() ??
    (isInputRequiredRuntimeState(runtimeState) ? "asked" : null);
  if (phase === "resolved") {
    const resolution = pickString(interrupt, ["resolution"])?.toLowerCase();
    if (resolution !== "replied" && resolution !== "rejected") {
      return null;
    }
    return {
      requestId,
      type: interruptType,
      phase: "resolved",
      resolution,
    };
  }
  if (phase !== "asked") {
    return null;
  }

  const details = asRecord(interrupt.details);
  if (interruptType === "permission") {
    return {
      requestId,
      type: "permission",
      phase: "asked",
      details: {
        permission: pickRawString(details, ["permission"]) ?? null,
        patterns: coerceStringArray(details?.patterns) ?? [],
      },
    };
  }
  if (interruptType === "question") {
    const rawQuestions = Array.isArray(details?.questions)
      ? details.questions
      : [];
    const questions = rawQuestions
      .map(parseInterruptQuestion)
      .filter((item): item is InterruptQuestion => Boolean(item));
    return {
      requestId,
      type: "question",
      phase: "asked",
      details: {
        questions,
      },
    };
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

const parseBlockType = (
  raw: string | null,
): "text" | "reasoning" | "tool_call" | null => {
  const normalized = (raw ?? "").trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "text") return "text";
  if (normalized === "reasoning") return "reasoning";
  if (normalized === "tool_call") return "tool_call";
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

const inferTaskIdFromMessageId = (messageId: string | null): string | null => {
  if (!messageId) return null;
  const normalized = messageId.trim();
  if (!normalized.startsWith("task:")) {
    return null;
  }
  const taskId = normalized.slice("task:".length).trim();
  return taskId.length > 0 ? taskId : null;
};

const buildFallbackEventId = ({
  messageId,
  artifactId,
  seq,
}: {
  messageId: string;
  artifactId: string;
  seq: number | null;
}) => {
  if (seq !== null) {
    return `seq:${messageId}:${seq}`;
  }
  return `chunk:${messageId}:${artifactId}`;
};

const extractSharedStreamMetadata = (
  artifactMetadata: Record<string, unknown> | null,
  rootMetadata: Record<string, unknown> | null,
) => mergeSharedMetadataSection([rootMetadata, artifactMetadata], "stream");

export const extractStreamBlockUpdate = (
  data: Record<string, unknown>,
): StreamBlockUpdate | null => {
  const kind = pickString(data, ["kind"]);
  if (kind && kind !== "artifact-update") {
    return null;
  }
  const artifact = asRecord(data.artifact);
  const rootMetadata = asRecord(data.metadata);
  const metadata = asRecord(artifact?.metadata) ?? rootMetadata;
  const sharedStream = extractSharedStreamMetadata(metadata, rootMetadata);
  const parts = Array.isArray(artifact?.parts) ? artifact.parts : [];
  const textFromParts = extractTextFromParts(parts);
  const dataFromParts = extractDataFromParts(parts);
  const rawBlockType =
    pickString(sharedStream, ["block_type"]) ??
    pickString(metadata, ["block_type"]) ??
    pickString(rootMetadata, ["block_type"]);
  const explicitBlockType = parseBlockType(rawBlockType);
  const blockType =
    explicitBlockType ??
    (rawBlockType === null && textFromParts ? "text" : null);
  if (!blockType) {
    return null;
  }

  const seq =
    pickInteger(data, ["seq"]) ??
    pickInteger(artifact ?? null, ["seq"]) ??
    pickInteger(metadata, ["seq"]) ??
    pickInteger(rootMetadata, ["seq"]) ??
    pickInteger(sharedStream, ["sequence", "seq"]);

  const artifactId =
    pickString(artifact ?? null, ["artifact_id", "artifactId", "id"]) ?? null;
  const taskIdHint =
    pickString(data, ["task_id", "taskId"]) ??
    pickString(artifact ?? null, ["task_id", "taskId"]) ??
    pickString(rootMetadata, ["task_id", "taskId"]) ??
    inferTaskIdFromArtifactId(artifactId);

  const upstreamMessageId =
    pickString(data, ["message_id", "messageId"]) ??
    pickString(artifact ?? null, ["message_id", "messageId"]) ??
    pickString(metadata, ["message_id", "messageId"]) ??
    pickString(rootMetadata, ["message_id", "messageId"]) ??
    pickString(sharedStream, ["message_id", "messageId"]);
  const resolvedMessageId =
    upstreamMessageId ?? (taskIdHint ? `task:${taskIdHint}` : null);
  const resolvedArtifactId =
    artifactId ?? `${resolvedMessageId ?? "stream"}:${blockType}`;
  const taskId =
    taskIdHint ??
    inferTaskIdFromArtifactId(resolvedArtifactId) ??
    inferTaskIdFromMessageId(resolvedMessageId) ??
    resolvedMessageId ??
    resolvedArtifactId;
  const messageId = resolvedMessageId ?? `artifact:${resolvedArtifactId}`;

  const delta =
    (blockType === "tool_call"
      ? dataFromParts || textFromParts
      : textFromParts) ||
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
  const upstreamEventId =
    pickString(data, ["event_id", "eventId"]) ??
    pickString(artifact ?? null, ["event_id", "eventId"]) ??
    pickString(metadata, ["event_id", "eventId"]) ??
    pickString(rootMetadata, ["event_id", "eventId"]) ??
    pickString(sharedStream, ["event_id", "eventId"]);
  const eventId = upstreamEventId
    ? upstreamEventId
    : buildFallbackEventId({
        messageId,
        artifactId: resolvedArtifactId,
        seq: seq ?? null,
      });
  const eventIdSource: StreamBlockUpdate["eventIdSource"] = upstreamEventId
    ? "upstream"
    : seq !== null
      ? "fallback_seq"
      : "fallback_chunk";

  const source =
    pickString(sharedStream, ["source"]) ??
    pickString(metadata, ["source"]) ??
    pickString(rootMetadata, ["source"]) ??
    null;
  const role = normalizeRole(
    pickString(data, ["role"]) ??
      pickString(sharedStream, ["role"]) ??
      pickString(metadata, ["role"]) ??
      pickString(rootMetadata, ["role"]),
  );

  return {
    eventId,
    eventIdSource,
    seq: seq ?? null,
    taskId,
    artifactId: resolvedArtifactId,
    blockType,
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
): MessageBlock[] => {
  const now = new Date().toISOString();
  const overwrite = update.source === "final_snapshot" || !update.append;
  const blocks = current ?? [];
  const lastBlock = blocks[blocks.length - 1];

  // Optimization: In-place update if we are appending to the same block type and it's not finished
  if (
    !overwrite &&
    lastBlock &&
    lastBlock.type === update.blockType &&
    !lastBlock.isFinished
  ) {
    lastBlock.content += update.delta;
    lastBlock.isFinished = update.done;
    lastBlock.updatedAt = now;
    return blocks;
  }

  // Fallback: Create new array for type switches, new blocks, or overwrites
  const nextBlocks = [...blocks];
  const lastNextBlock = nextBlocks[nextBlocks.length - 1];

  if (overwrite) {
    if (
      lastNextBlock &&
      lastNextBlock.type === update.blockType &&
      !lastNextBlock.isFinished
    ) {
      nextBlocks[nextBlocks.length - 1] = {
        ...lastNextBlock,
        content: update.delta,
        isFinished: update.done,
        updatedAt: now,
      };
      return nextBlocks;
    }
    if (lastNextBlock && !lastNextBlock.isFinished) {
      nextBlocks[nextBlocks.length - 1] = {
        ...lastNextBlock,
        isFinished: true,
        updatedAt: now,
      };
    }
    nextBlocks.push({
      id: `${update.messageId}:${nextBlocks.length + 1}`,
      type: update.blockType,
      content: update.delta,
      isFinished: update.done,
      createdAt: now,
      updatedAt: now,
    });
    return nextBlocks;
  }

  // Type mismatch or new block needed
  if (lastNextBlock && !lastNextBlock.isFinished) {
    nextBlocks[nextBlocks.length - 1] = {
      ...lastNextBlock,
      isFinished: true,
      updatedAt: now,
    };
  }

  nextBlocks.push({
    id: `${update.messageId}:${nextBlocks.length + 1}`,
    type: update.blockType,
    content: update.delta,
    isFinished: update.done,
    createdAt: now,
    updatedAt: now,
  });
  return nextBlocks;
};

export const projectPrimaryTextContent = (
  blocks: MessageBlock[] | undefined,
): string =>
  (blocks ?? [])
    .filter((block) => block.type === "text")
    .map((block) => block.content)
    .join("");

export const applyLoadedBlockDetail = (
  message: Pick<ChatMessage, "content" | "blocks">,
  input: {
    blockId: string;
    type?: string;
    content?: string | null;
    isFinished?: boolean;
  },
): Pick<ChatMessage, "content" | "blocks"> => {
  const nextBlocks = (message.blocks ?? []).map((block) =>
    block.id === input.blockId
      ? {
          ...block,
          type:
            typeof input.type === "string" && input.type.trim().length > 0
              ? input.type
              : block.type,
          content: typeof input.content === "string" ? input.content : "",
          isFinished:
            typeof input.isFinished === "boolean"
              ? input.isFinished
              : block.isFinished,
        }
      : block,
  );

  const hasTextBlocks = nextBlocks.some((block) => block.type === "text");
  return {
    blocks: nextBlocks,
    content: hasTextBlocks
      ? projectPrimaryTextContent(nextBlocks)
      : message.content,
  };
};

export const finalizeMessageBlocks = (
  blocks: MessageBlock[] | undefined,
): MessageBlock[] | undefined => {
  if (!blocks || blocks.length === 0) {
    return blocks;
  }
  const nextBlocks = [...blocks];
  const lastBlock = nextBlocks[nextBlocks.length - 1];
  if (!lastBlock || lastBlock.isFinished) {
    return nextBlocks;
  }
  nextBlocks[nextBlocks.length - 1] = {
    ...lastBlock,
    isFinished: true,
    updatedAt: new Date().toISOString(),
  };
  return nextBlocks;
};
