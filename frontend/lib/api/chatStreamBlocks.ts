import type {
  InterruptType,
  PendingRuntimeInterrupt,
  RuntimeInterrupt,
  StreamMissingParam,
} from "./chatRuntimeStatus";
import { asRecord, pickRawString, pickString } from "./chatUtilsShared";
import { extractHubStreamEnvelope } from "./hubStreamEnvelope";

export type ChatRole = "user" | "agent" | "system";

export type ToolCallView = {
  name?: string | null;
  status:
    | "running"
    | "completed"
    | "success"
    | "failed"
    | "interrupted"
    | "unknown";
  callId?: string | null;
  arguments?: unknown;
  result?: unknown;
  error?: unknown;
};

export type ToolCallTimelineEntry = {
  status: string;
  title?: string | null;
  input?: unknown;
  output?: unknown;
  error?: unknown;
};

export type ToolCallDetailView = ToolCallView & {
  title?: string | null;
  timeline?: ToolCallTimelineEntry[] | null;
  raw?: string | null;
};

export type MessageBlock = {
  id: string;
  type: string;
  content: string;
  isFinished: boolean;
  blockId?: string;
  laneId?: string;
  baseSeq?: number | null;
  toolCall?: ToolCallView | null;
  toolCallDetail?: ToolCallDetailView | null;
  interrupt?: RuntimeInterrupt | null;
  createdAt: string;
  updatedAt: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  kind?: string;
  content: string;
  createdAt: string;
  status?: "streaming" | "done" | "error" | "interrupted";
  operationId?: string | null;
  blocks?: MessageBlock[];
  errorCode?: string | null;
  errorMessage?: string | null;
  errorSource?: string | null;
  jsonrpcCode?: number | null;
  missingParams?: StreamMissingParam[] | null;
  upstreamError?: Record<string, unknown> | null;
};

export type StreamBlockUpdate = {
  eventId: string;
  eventIdSource: "upstream" | "fallback_seq" | "fallback_chunk";
  messageIdSource: "upstream" | "task_fallback" | "artifact_fallback";
  seq: number | null;
  taskId: string;
  artifactId: string;
  blockId: string;
  laneId: string;
  blockType: "text" | "reasoning" | "tool_call" | "interrupt_event";
  op: "append" | "replace" | "finalize";
  baseSeq: number | null;
  source: string | null;
  messageId: string;
  role: ChatRole;
  delta: string;
  append: boolean;
  done: boolean;
  toolCall?: ToolCallView | null;
  interrupt?: RuntimeInterrupt | null;
};

const finalizeRunningToolCallView = (
  toolCall: ToolCallView | null | undefined,
): ToolCallView | null | undefined =>
  toolCall?.status === "running"
    ? { ...toolCall, status: "completed" }
    : toolCall;

const BLOCK_OPERATION_TYPES = new Set(["append", "replace", "finalize"]);
const buildInterruptEventMessageCode = (
  interrupt: RuntimeInterrupt,
):
  | "permission_requested"
  | "permission_resolved"
  | "permission_expired"
  | "permissions_requested"
  | "permissions_resolved"
  | "permissions_expired"
  | "question_requested"
  | "question_answer_received"
  | "question_rejected"
  | "question_expired" => {
  if (interrupt.phase === "resolved") {
    if (interrupt.resolution === "expired") {
      if (interrupt.type === "permission") {
        return "permission_expired";
      }
      if (interrupt.type === "permissions") {
        return "permissions_expired";
      }
      return "question_expired";
    }
    if (interrupt.type === "permission") {
      return "permission_resolved";
    }
    if (interrupt.type === "permissions") {
      return "permissions_resolved";
    }
    if (interrupt.type === "elicitation") {
      return interrupt.resolution === "rejected"
        ? "question_rejected"
        : "question_answer_received";
    }
    if (interrupt.resolution === "rejected") {
      return "question_rejected";
    }
    return "question_answer_received";
  }
  if (interrupt.type === "permission") {
    return "permission_requested";
  }
  if (interrupt.type === "permissions") {
    return "permissions_requested";
  }
  return "question_requested";
};

const isInterruptQuestionOption = (
  value: unknown,
): value is {
  label: string;
  description?: string | null;
  value?: string | null;
} => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const candidate = value as {
    label?: unknown;
    description?: unknown;
    value?: unknown;
  };
  return (
    typeof candidate.label === "string" &&
    (candidate.description === undefined ||
      candidate.description === null ||
      typeof candidate.description === "string") &&
    (candidate.value === undefined ||
      candidate.value === null ||
      typeof candidate.value === "string")
  );
};

const isInterruptQuestion = (
  value: unknown,
): value is {
  question: string;
  header?: string | null;
  description?: string | null;
  options?: unknown[];
} => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const candidate = value as {
    question?: unknown;
    header?: unknown;
    description?: unknown;
    options?: unknown;
  };
  return (
    typeof candidate.question === "string" &&
    (candidate.header === undefined ||
      candidate.header === null ||
      typeof candidate.header === "string") &&
    (candidate.description === undefined ||
      candidate.description === null ||
      typeof candidate.description === "string") &&
    (candidate.options === undefined ||
      (Array.isArray(candidate.options) &&
        candidate.options.every(isInterruptQuestionOption)))
  );
};

const isRuntimeInterrupt = (value: unknown): value is RuntimeInterrupt => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const candidate = value as RuntimeInterrupt;
  const isInterruptType = (
    input: RuntimeInterrupt["type"],
  ): input is InterruptType =>
    input === "permission" ||
    input === "question" ||
    input === "permissions" ||
    input === "elicitation";
  if (
    typeof candidate.requestId !== "string" ||
    !isInterruptType(candidate.type)
  ) {
    return false;
  }
  if (candidate.phase === "resolved") {
    return (
      candidate.resolution === "replied" ||
      candidate.resolution === "rejected" ||
      candidate.resolution === "expired"
    );
  }
  if (candidate.phase !== "asked") {
    return false;
  }
  const details = candidate.details;
  if (!details || typeof details !== "object" || Array.isArray(details)) {
    return false;
  }
  return (
    (details.permission === undefined ||
      details.permission === null ||
      typeof details.permission === "string") &&
    (details.patterns === undefined ||
      (Array.isArray(details.patterns) &&
        details.patterns.every((item) => typeof item === "string"))) &&
    (details.displayMessage === undefined ||
      details.displayMessage === null ||
      typeof details.displayMessage === "string") &&
    (details.questions === undefined ||
      (Array.isArray(details.questions) &&
        details.questions.every(isInterruptQuestion))) &&
    (details.permissions === undefined ||
      details.permissions === null ||
      (typeof details.permissions === "object" &&
        !Array.isArray(details.permissions))) &&
    (details.serverName === undefined ||
      details.serverName === null ||
      typeof details.serverName === "string") &&
    (details.mode === undefined ||
      details.mode === null ||
      typeof details.mode === "string") &&
    (details.url === undefined ||
      details.url === null ||
      typeof details.url === "string") &&
    (details.elicitationId === undefined ||
      details.elicitationId === null ||
      typeof details.elicitationId === "string") &&
    (details.meta === undefined ||
      details.meta === null ||
      (typeof details.meta === "object" && !Array.isArray(details.meta)))
  );
};

const stringifyInterruptObject = (value: unknown): string | null => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return null;
  }
};

const buildInterruptEventContent = (interrupt: RuntimeInterrupt): string => {
  const messageCode = buildInterruptEventMessageCode(interrupt);
  if (messageCode === "permission_expired") {
    return "Permission request expired. Interrupt closed.";
  }
  if (messageCode === "permissions_expired") {
    return "Permissions request expired. Interrupt closed.";
  }
  if (messageCode === "permission_resolved") {
    return "Permission request was handled. Agent resumed.";
  }
  if (messageCode === "permissions_resolved") {
    return "Permissions request was handled. Agent resumed.";
  }
  if (messageCode === "question_expired") {
    if (interrupt.type === "elicitation") {
      return "Additional input request expired. Interrupt closed.";
    }
    return "Question request expired. Interrupt closed.";
  }
  if (messageCode === "question_rejected") {
    if (interrupt.type === "elicitation") {
      return "Additional input request was declined. Interrupt closed.";
    }
    return "Question request was rejected. Interrupt closed.";
  }
  if (messageCode === "question_answer_received") {
    if (interrupt.type === "elicitation") {
      return "Additional input was submitted. Agent resumed.";
    }
    return "Question answer received. Agent resumed.";
  }

  const askedInterrupt = interrupt as PendingRuntimeInterrupt;

  if (messageCode === "permission_requested") {
    const displayMessage =
      askedInterrupt.details.displayMessage?.trim() || null;
    const permission = askedInterrupt.details.permission?.trim() || "unknown";
    const patterns = askedInterrupt.details.patterns ?? [];
    const baseMessage =
      displayMessage || `Agent requested permission: ${permission}.`;
    if (patterns.length > 0) {
      return `${baseMessage}\nTargets: ${patterns.join(", ")}`;
    }
    return baseMessage;
  }
  if (messageCode === "permissions_requested") {
    const displayMessage =
      askedInterrupt.details.displayMessage?.trim() || null;
    const permissionsText =
      stringifyInterruptObject(askedInterrupt.details.permissions) ?? null;
    if (displayMessage && permissionsText) {
      return `${displayMessage}\nRequested permissions: ${permissionsText}`;
    }
    if (displayMessage) {
      return displayMessage;
    }
    if (permissionsText) {
      return `Agent requested permissions approval: ${permissionsText}`;
    }
    return "Agent requested permissions approval.";
  }
  if (askedInterrupt.type === "elicitation") {
    const displayMessage =
      askedInterrupt.details.displayMessage?.trim() || null;
    const lines = [
      displayMessage || "Agent requested additional structured input.",
    ];
    if (askedInterrupt.details.mode?.trim()) {
      lines.push(`Mode: ${askedInterrupt.details.mode.trim()}`);
    }
    if (askedInterrupt.details.serverName?.trim()) {
      lines.push(`Server: ${askedInterrupt.details.serverName.trim()}`);
    }
    if (askedInterrupt.details.url?.trim()) {
      lines.push(`URL: ${askedInterrupt.details.url.trim()}`);
    }
    return lines.join("\n");
  }

  const displayMessage = askedInterrupt.details.displayMessage?.trim() || null;
  const questionEntries = (askedInterrupt.details.questions ?? [])
    .map((question) => {
      const prompt = question.question.trim();
      if (!prompt) {
        return null;
      }
      const description = question.description?.trim() || null;
      return { prompt, description };
    })
    .filter(
      (
        question,
      ): question is {
        prompt: string;
        description: string | null;
      } => Boolean(question),
    );
  if (questionEntries.length === 1) {
    const entry = questionEntries[0];
    if (displayMessage) {
      const lines = [displayMessage, `Question: ${entry.prompt}`];
      if (entry.description) {
        lines.push(`Details: ${entry.description}`);
      }
      return lines.join("\n");
    }
    if (entry.description) {
      return `Agent requested additional input: ${entry.prompt}\nDetails: ${entry.description}`;
    }
    return `Agent requested additional input: ${entry.prompt}`;
  }
  if (questionEntries.length > 1) {
    const lines = questionEntries.map((entry) =>
      entry.description
        ? `- ${entry.prompt} (${entry.description})`
        : `- ${entry.prompt}`,
    );
    if (displayMessage) {
      return `${displayMessage}\n${lines.join("\n")}`;
    }
    return `Agent requested additional input:\n${lines.join("\n")}`;
  }
  if (displayMessage) {
    return displayMessage;
  }
  return "Agent requested additional input.";
};

export const buildInterruptEventBlockUpdate = ({
  interrupt,
  messageId,
}: {
  interrupt: RuntimeInterrupt;
  messageId: string;
}): StreamBlockUpdate => {
  const normalizedMessageId = messageId.trim();
  const eventId = `interrupt:${interrupt.requestId}:${interrupt.phase}`;
  return {
    eventId,
    eventIdSource: "upstream",
    messageIdSource: "upstream",
    seq: null,
    taskId: `interrupt:${normalizedMessageId}`,
    artifactId: `${normalizedMessageId}:interrupt:${interrupt.requestId}:${interrupt.phase}`,
    blockId: `${normalizedMessageId}:interrupt:${interrupt.requestId}`,
    laneId: "interrupt_event",
    blockType: "interrupt_event",
    op: "replace",
    baseSeq: null,
    source: "interrupt_lifecycle",
    messageId: normalizedMessageId,
    role: "agent",
    delta: buildInterruptEventContent(interrupt),
    append: false,
    done: true,
    interrupt,
  };
};

const parseSerializedInterruptEventContent = (
  raw: string,
): { content: string; interrupt: RuntimeInterrupt | null } => {
  try {
    const payload = JSON.parse(raw) as {
      kind?: unknown;
      content?: unknown;
      interrupt?: unknown;
    };
    if (payload.kind !== "interrupt_event") {
      return { content: raw, interrupt: null };
    }
    const content =
      typeof payload.content === "string" && payload.content.trim().length > 0
        ? payload.content
        : raw;
    const interrupt = isRuntimeInterrupt(payload.interrupt)
      ? payload.interrupt
      : null;
    return { content, interrupt };
  } catch {
    return { content: raw, interrupt: null };
  }
};

const normalizeRole = (raw: string | null): ChatRole => {
  let role = (raw ?? "").trim().toLowerCase().replace(/_/g, "-");
  if (role.startsWith("role-")) {
    role = role.slice("role-".length);
  }
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
): "text" | "reasoning" | "tool_call" | "interrupt_event" | null => {
  const normalized = (raw ?? "").trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "text") return "text";
  if (normalized === "reasoning") return "reasoning";
  if (normalized === "tool_call") return "tool_call";
  if (normalized === "interrupt_event") return "interrupt_event";
  return null;
};

const parseBlockOperation = (
  raw: string | null,
): "append" | "replace" | "finalize" | null => {
  const normalized = (raw ?? "").trim().toLowerCase();
  return BLOCK_OPERATION_TYPES.has(normalized)
    ? (normalized as "append" | "replace" | "finalize")
    : null;
};

const findBlockIndexByBlockId = (
  blocks: MessageBlock[],
  blockId: string,
): number => blocks.findIndex((block) => block.blockId === blockId);

const adaptStreamBlockUpdateForReducer = (
  _current: MessageBlock[] | undefined,
  update: StreamBlockUpdate,
): StreamBlockUpdate => update;

export const extractStreamBlockUpdate = (
  data: Record<string, unknown>,
): StreamBlockUpdate | null => {
  const hub = extractHubStreamEnvelope(data);
  const streamBlock = hub?.streamBlock;
  if (!streamBlock) {
    return null;
  }
  const blockType = parseBlockType(pickString(streamBlock, ["blockType"]));
  if (!blockType) {
    return null;
  }
  const op = parseBlockOperation(pickString(streamBlock, ["op"]));
  if (!op) {
    return null;
  }

  const eventId = pickString(streamBlock, ["eventId"]);
  const messageId = pickString(streamBlock, ["messageId"]);
  const taskId = pickString(streamBlock, ["taskId"]);
  const artifactId = pickString(streamBlock, ["artifactId"]);
  const blockId = pickString(streamBlock, ["blockId"]);
  const laneId = pickString(streamBlock, ["laneId"]);
  if (!eventId || !messageId || !taskId || !artifactId || !blockId || !laneId) {
    return null;
  }
  const delta = pickRawString(streamBlock, ["delta"]) ?? "";
  if (!delta && op !== "finalize") {
    return null;
  }
  const toolCall = asRecord(streamBlock.toolCall);
  const interruptPayload =
    blockType === "interrupt_event"
      ? parseSerializedInterruptEventContent(delta)
      : { content: delta, interrupt: null };

  return {
    eventId,
    eventIdSource:
      streamBlock.eventIdSource === "upstream" ||
      streamBlock.eventIdSource === "fallback_seq" ||
      streamBlock.eventIdSource === "fallback_chunk"
        ? streamBlock.eventIdSource
        : "fallback_chunk",
    messageIdSource:
      streamBlock.messageIdSource === "upstream" ||
      streamBlock.messageIdSource === "task_fallback" ||
      streamBlock.messageIdSource === "artifact_fallback"
        ? streamBlock.messageIdSource
        : "artifact_fallback",
    seq: typeof streamBlock.seq === "number" ? streamBlock.seq : null,
    taskId,
    artifactId,
    blockId,
    laneId,
    blockType,
    op,
    baseSeq:
      typeof streamBlock.baseSeq === "number" ? streamBlock.baseSeq : null,
    source: pickString(streamBlock, ["source"]),
    messageId,
    role: normalizeRole(pickString(streamBlock, ["role"])),
    delta: interruptPayload.content,
    append:
      typeof streamBlock.append === "boolean"
        ? streamBlock.append
        : op === "append",
    done:
      typeof streamBlock.done === "boolean"
        ? streamBlock.done
        : op === "finalize",
    toolCall:
      blockType === "tool_call"
        ? ((toolCall as ToolCallView | null) ?? null)
        : null,
    interrupt: interruptPayload.interrupt,
  };
};

export const applyStreamBlockUpdate = (
  current: MessageBlock[] | undefined,
  update: StreamBlockUpdate,
): MessageBlock[] => {
  const resolvedUpdate = adaptStreamBlockUpdateForReducer(current, update);
  const now = new Date().toISOString();
  const blocks = current ?? [];
  const nextBlocks = [...blocks];
  const lastNextBlock = nextBlocks[nextBlocks.length - 1];
  const targetIndex = findBlockIndexByBlockId(
    nextBlocks,
    resolvedUpdate.blockId,
  );
  const delta = resolvedUpdate.delta;

  const applyBlockPatch = (index: number, content: string) => {
    const targetBlock = nextBlocks[index];
    const currentBaseSeq = targetBlock.baseSeq ?? null;
    if (
      resolvedUpdate.baseSeq !== null &&
      currentBaseSeq !== null &&
      resolvedUpdate.baseSeq < currentBaseSeq
    ) {
      return nextBlocks;
    }
    const shouldPreserveInterruptEventContent =
      resolvedUpdate.blockType === "interrupt_event" &&
      resolvedUpdate.interrupt?.phase === "resolved" &&
      targetBlock.type === "interrupt_event" &&
      typeof targetBlock.content === "string" &&
      targetBlock.content.trim().length > 0;
    const nextToolCall =
      resolvedUpdate.toolCall !== undefined
        ? resolvedUpdate.done
          ? (finalizeRunningToolCallView(resolvedUpdate.toolCall) ?? null)
          : (resolvedUpdate.toolCall ?? null)
        : targetBlock.toolCall !== undefined
          ? resolvedUpdate.done
            ? (finalizeRunningToolCallView(targetBlock.toolCall) ?? null)
            : (targetBlock.toolCall ?? null)
          : undefined;
    nextBlocks[index] = {
      ...targetBlock,
      type: resolvedUpdate.blockType,
      blockId: resolvedUpdate.blockId,
      laneId: resolvedUpdate.laneId,
      baseSeq: resolvedUpdate.baseSeq ?? currentBaseSeq,
      content: shouldPreserveInterruptEventContent
        ? targetBlock.content
        : content,
      isFinished: resolvedUpdate.done,
      ...(nextToolCall !== undefined ? { toolCall: nextToolCall } : {}),
      ...(resolvedUpdate.interrupt !== undefined
        ? { interrupt: resolvedUpdate.interrupt ?? null }
        : targetBlock.interrupt !== undefined
          ? { interrupt: targetBlock.interrupt ?? null }
          : {}),
      updatedAt: now,
    };
    return nextBlocks;
  };

  const closeActiveBlock = () => {
    if (lastNextBlock && !lastNextBlock.isFinished) {
      nextBlocks[nextBlocks.length - 1] = {
        ...lastNextBlock,
        isFinished: true,
        ...(lastNextBlock.toolCall !== undefined
          ? {
              toolCall:
                finalizeRunningToolCallView(lastNextBlock.toolCall) ?? null,
            }
          : {}),
        updatedAt: now,
      };
    }
  };

  const pushNewBlock = (content: string) => {
    const nextToolCall =
      resolvedUpdate.toolCall !== undefined
        ? resolvedUpdate.done
          ? (finalizeRunningToolCallView(resolvedUpdate.toolCall) ?? null)
          : (resolvedUpdate.toolCall ?? null)
        : undefined;
    nextBlocks.push({
      id: `${resolvedUpdate.messageId}:${nextBlocks.length + 1}`,
      type: resolvedUpdate.blockType,
      blockId: resolvedUpdate.blockId,
      laneId: resolvedUpdate.laneId,
      baseSeq: resolvedUpdate.baseSeq,
      content,
      isFinished: resolvedUpdate.done,
      ...(nextToolCall !== undefined ? { toolCall: nextToolCall } : {}),
      ...(resolvedUpdate.interrupt !== undefined
        ? { interrupt: resolvedUpdate.interrupt ?? null }
        : {}),
      createdAt: now,
      updatedAt: now,
    });
    return nextBlocks;
  };

  if (resolvedUpdate.op === "finalize") {
    return targetIndex >= 0
      ? applyBlockPatch(targetIndex, nextBlocks[targetIndex]?.content ?? "")
      : nextBlocks;
  }

  if (resolvedUpdate.op === "append") {
    if (targetIndex >= 0) {
      const targetBlock = nextBlocks[targetIndex];
      return applyBlockPatch(
        targetIndex,
        `${targetBlock?.content ?? ""}${delta}`,
      );
    }
    closeActiveBlock();
    return pushNewBlock(delta);
  }

  if (targetIndex >= 0) {
    return applyBlockPatch(targetIndex, delta);
  }

  closeActiveBlock();
  return pushNewBlock(delta);
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
    toolCall?: ToolCallView | null;
    toolCallDetail?: ToolCallDetailView | null;
    interrupt?: RuntimeInterrupt | null;
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
          toolCall:
            input.toolCall === undefined
              ? (block.toolCall ?? null)
              : input.toolCall,
          toolCallDetail:
            input.toolCallDetail === undefined
              ? (block.toolCallDetail ?? null)
              : input.toolCallDetail,
          interrupt:
            input.interrupt === undefined
              ? (block.interrupt ?? null)
              : input.interrupt,
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
    ...(lastBlock.toolCall !== undefined
      ? {
          toolCall: finalizeRunningToolCallView(lastBlock.toolCall) ?? null,
        }
      : {}),
    updatedAt: new Date().toISOString(),
  };
  return nextBlocks;
};
