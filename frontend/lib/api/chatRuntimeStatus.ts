import {
  asRecord,
  coerceStringArray,
  pickFirstArray,
  pickInt,
  pickInteger,
  pickNestedRawString,
  pickRawString,
  pickString,
  resolveNestedValue,
} from "./chatUtilsShared";

import {
  getPreferredInterruptMetadata,
  getPreferredSessionMetadata,
} from "@/lib/sharedMetadata";

export type StreamMissingParam = {
  name: string;
  required: boolean;
};

export type StreamErrorDetails = {
  errorCode: string | null;
  source: string | null;
  jsonrpcCode: number | null;
  missingParams: StreamMissingParam[] | null;
  upstreamError: Record<string, unknown> | null;
};

type ParsedStreamError = StreamErrorDetails & {
  message: string;
};

type RuntimeStatusEvent = {
  state: string;
  isFinal: boolean;
  interrupt: RuntimeInterrupt | null;
  seq: number | null;
  completionPhase: "persisted" | null;
  messageId: string | null;
};

export type RuntimeStatusContract = {
  version: "v1";
  canonicalStates: readonly string[];
  terminalStates: readonly string[];
  finalStates: readonly string[];
  interactiveStates: readonly string[];
  failureStates: readonly string[];
  aliases: Readonly<Record<string, string>>;
  passthroughUnknown: true;
};

export const DEFAULT_RUNTIME_STATUS_CONTRACT: RuntimeStatusContract = {
  version: "v1",
  canonicalStates: [
    "working",
    "input-required",
    "auth-required",
    "completed",
    "failed",
    "cancelled",
  ],
  terminalStates: [
    "input-required",
    "auth-required",
    "completed",
    "failed",
    "cancelled",
  ],
  finalStates: ["completed", "failed", "cancelled"],
  interactiveStates: ["input-required", "auth-required"],
  failureStates: ["failed", "cancelled"],
  aliases: {
    input_required: "input-required",
    auth_required: "auth-required",
    canceled: "cancelled",
    done: "completed",
    success: "completed",
    error: "failed",
    rejected: "failed",
  },
  passthroughUnknown: true,
};

const resolveStatusUpdateBody = (
  data: Record<string, unknown>,
): Record<string, unknown> | null => asRecord(data.statusUpdate);

const resolveCanonicalStreamBody = (
  data: Record<string, unknown>,
): Record<string, unknown> | null =>
  asRecord(data.artifactUpdate) ??
  asRecord(data.message) ??
  asRecord(data.statusUpdate) ??
  asRecord(data.task);

type InterruptQuestionOption = {
  label: string;
  description: string | null;
  value: string | null;
};

type InterruptQuestion = {
  header: string | null;
  description?: string | null;
  question: string;
  options: InterruptQuestionOption[];
};

export type InterruptType =
  | "permission"
  | "question"
  | "permissions"
  | "elicitation";

type RuntimeInterruptDetails = {
  permission?: string | null;
  patterns?: string[];
  displayMessage?: string | null;
  questions?: InterruptQuestion[];
  permissions?: Record<string, unknown> | null;
  serverName?: string | null;
  mode?: string | null;
  requestedSchema?: unknown;
  url?: string | null;
  elicitationId?: string | null;
  meta?: Record<string, unknown> | null;
};

type RuntimeInterruptBase = {
  requestId: string;
  type: InterruptType;
  source?: "stream" | "recovery";
  sessionId?: string | null;
  taskId?: string | null;
  contextId?: string | null;
  expiresAt?: number | null;
};

export type PendingRuntimeInterrupt = RuntimeInterruptBase & {
  phase: "asked";
  details: RuntimeInterruptDetails;
};

export type ResolvedRuntimeInterrupt = RuntimeInterruptBase & {
  phase: "resolved";
  resolution: "replied" | "rejected" | "expired";
};

export type RuntimeInterrupt =
  | PendingRuntimeInterrupt
  | ResolvedRuntimeInterrupt;

const normalizeRuntimeAliasMap = (
  contract: RuntimeStatusContract,
): Record<string, string> =>
  Object.entries(contract.aliases).reduce<Record<string, string>>(
    (acc, [alias, canonical]) => {
      acc[alias.trim().toLowerCase().replace(/_/g, "-")] = canonical;
      return acc;
    },
    {},
  );

const resolveRuntimeStatusContract = (
  contract?: RuntimeStatusContract | null,
): RuntimeStatusContract => contract ?? DEFAULT_RUNTIME_STATUS_CONTRACT;

const normalizeMissingParam = (value: unknown): StreamMissingParam | null => {
  if (typeof value === "string" && value.trim().length > 0) {
    return {
      name: value.trim(),
      required: true,
    };
  }
  const record = asRecord(value);
  if (!record) {
    return null;
  }
  const name =
    pickString(record, ["name", "field", "param", "id"]) ??
    pickRawString(record, ["name", "field", "param", "id"]);
  if (!name) {
    return null;
  }
  return {
    name,
    required: typeof record.required === "boolean" ? record.required : true,
  };
};

const coerceMissingParams = (value: unknown): StreamMissingParam[] | null => {
  if (value === null || value === undefined) {
    return null;
  }
  const entries = Array.isArray(value) ? value : [value];
  const normalized = entries
    .map((entry) => normalizeMissingParam(entry))
    .filter((entry): entry is StreamMissingParam => Boolean(entry));
  if (!normalized.length) {
    return null;
  }
  const unique = new Map<string, StreamMissingParam>();
  normalized.forEach((entry) => {
    if (!unique.has(entry.name)) {
      unique.set(entry.name, entry);
    }
  });
  return Array.from(unique.values());
};

export const extractSessionMeta = (data: Record<string, unknown>) => {
  const body = resolveCanonicalStreamBody(data) ?? data;
  const session = getPreferredSessionMetadata(body);
  const properties = asRecord(body.properties);
  const metadata = asRecord(body.metadata);
  const shared = asRecord(metadata?.shared);
  const sharedStream = asRecord(shared?.stream);
  const externalSessionId =
    pickString(session, ["id", "externalSessionId"]) ?? undefined;
  const rawProvider = pickString(session, ["provider"]);
  const provider = rawProvider?.trim().toLowerCase() ?? undefined;
  const streamThreadId =
    pickString(properties, ["thread_id", "threadId"]) ??
    pickString(sharedStream, ["thread_id", "threadId"]) ??
    pickString(body, ["thread_id", "threadId"]) ??
    undefined;
  const streamTurnId =
    pickString(properties, ["turn_id", "turnId"]) ??
    pickString(sharedStream, ["turn_id", "turnId"]) ??
    pickString(body, ["turn_id", "turnId"]) ??
    undefined;
  const transport =
    typeof body.transport === "string"
      ? body.transport
      : typeof data.transport === "string"
        ? data.transport
        : undefined;
  const inputModes =
    coerceStringArray(body.input_modes) ??
    coerceStringArray(body.inputModes) ??
    coerceStringArray(data.input_modes) ??
    coerceStringArray(data.inputModes);
  const outputModes =
    coerceStringArray(body.output_modes) ??
    coerceStringArray(body.outputModes) ??
    coerceStringArray(data.output_modes) ??
    coerceStringArray(data.outputModes);

  return {
    provider,
    externalSessionId,
    streamThreadId,
    streamTurnId,
    transport,
    inputModes,
    outputModes,
  };
};

const extractInterruptDisplayMessage = (
  details: Record<string, unknown> | null,
): string | null =>
  pickRawString(details, [
    "displayMessage",
    "display_message",
    "message",
    "description",
    "prompt",
    "reason",
    "request",
    "context",
  ]) ??
  pickNestedRawString(details, [
    ["request", "message"],
    ["request", "description"],
    ["request", "prompt"],
    ["request", "reason"],
    ["context", "message"],
    ["context", "description"],
    ["context", "prompt"],
    ["context", "reason"],
    ["prompt", "message"],
    ["prompt", "description"],
  ]);

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
  const prompt =
    pickString(question, ["question", "prompt", "message"]) ??
    pickNestedRawString(question, [
      ["request", "question"],
      ["request", "prompt"],
      ["request", "message"],
      ["context", "question"],
      ["context", "prompt"],
      ["context", "message"],
      ["prompt", "question"],
      ["prompt", "message"],
    ]);
  if (!prompt) {
    return null;
  }
  const rawOptions = pickFirstArray(question, [
    ["options"],
    ["request", "options"],
    ["context", "options"],
    ["prompt", "options"],
  ]);
  const options = rawOptions
    .map(parseInterruptQuestionOption)
    .filter((item): item is InterruptQuestionOption => Boolean(item));
  return {
    header:
      pickRawString(question, ["header", "title"]) ??
      pickNestedRawString(question, [
        ["request", "header"],
        ["request", "title"],
        ["context", "header"],
        ["context", "title"],
      ]) ??
      null,
    description:
      pickRawString(question, [
        "description",
        "hint",
        "help_text",
        "helpText",
      ]) ??
      pickNestedRawString(question, [
        ["request", "description"],
        ["context", "description"],
        ["prompt", "description"],
      ]) ??
      null,
    question: prompt,
    options,
  };
};

export const normalizeRuntimeState = (
  state: string,
  contract?: RuntimeStatusContract | null,
) => {
  const resolvedContract = resolveRuntimeStatusContract(contract);
  let normalized = state.trim().toLowerCase().replace(/_/g, "-");
  if (normalized.startsWith("task-state-")) {
    normalized = normalized.slice("task-state-".length);
  }
  const aliases = normalizeRuntimeAliasMap(resolvedContract);
  return aliases[normalized] ?? normalized;
};

export const isInputRequiredRuntimeState = (
  state: string,
  contract?: RuntimeStatusContract | null,
) => {
  const resolvedContract = resolveRuntimeStatusContract(contract);
  const interactiveStates = resolvedContract.interactiveStates.map((item) =>
    normalizeRuntimeState(item, resolvedContract),
  );
  const normalized = normalizeRuntimeState(state, resolvedContract);
  return interactiveStates.includes(normalized);
};

const extractRuntimeInterrupt = (
  data: Record<string, unknown>,
  runtimeState: string,
  contract?: RuntimeStatusContract | null,
): RuntimeInterrupt | null => {
  const interrupt = getPreferredInterruptMetadata(data);
  if (!interrupt) {
    return null;
  }
  const requestId = pickString(interrupt, ["request_id", "requestId"]);
  const interruptType = pickString(interrupt, ["type"])?.toLowerCase();
  if (
    !requestId ||
    (interruptType !== "permission" &&
      interruptType !== "question" &&
      interruptType !== "permissions" &&
      interruptType !== "elicitation")
  ) {
    return null;
  }

  const phase =
    pickString(interrupt, ["phase"])?.toLowerCase() ??
    (isInputRequiredRuntimeState(runtimeState, contract) ? "asked" : null);
  if (phase === "resolved") {
    const resolution = pickString(interrupt, ["resolution"])?.toLowerCase();
    if (
      resolution !== "replied" &&
      resolution !== "rejected" &&
      resolution !== "expired"
    ) {
      return null;
    }
    return {
      requestId,
      type: interruptType,
      phase: "resolved",
      resolution,
      source: "stream",
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
      source: "stream",
      details: {
        permission: pickRawString(details, ["permission"]) ?? null,
        patterns: coerceStringArray(details?.patterns) ?? [],
        displayMessage: extractInterruptDisplayMessage(details),
      },
    };
  }
  if (interruptType === "permissions") {
    return {
      requestId,
      type: "permissions",
      phase: "asked",
      source: "stream",
      details: {
        permissions: asRecord(details?.permissions),
        displayMessage: extractInterruptDisplayMessage(details),
      },
    };
  }
  if (interruptType === "question") {
    const rawQuestions = pickFirstArray(details, [
      ["questions"],
      ["request", "questions"],
      ["context", "questions"],
    ]);
    const questions = rawQuestions
      .map(parseInterruptQuestion)
      .filter((item): item is InterruptQuestion => Boolean(item));
    return {
      requestId,
      type: "question",
      phase: "asked",
      source: "stream",
      details: {
        displayMessage: extractInterruptDisplayMessage(details),
        questions,
      },
    };
  }
  if (interruptType === "elicitation") {
    return {
      requestId,
      type: "elicitation",
      phase: "asked",
      source: "stream",
      details: {
        displayMessage: extractInterruptDisplayMessage(details),
        serverName:
          pickRawString(details, ["server_name", "serverName"]) ?? null,
        mode: pickRawString(details, ["mode"]) ?? null,
        requestedSchema:
          details?.requested_schema ?? details?.requestedSchema ?? null,
        url: pickRawString(details, ["url"]) ?? null,
        elicitationId:
          pickRawString(details, ["elicitation_id", "elicitationId"]) ?? null,
        meta: asRecord(details?.meta),
      },
    };
  }
  return null;
};

export const extractRuntimeStatusEvent = (
  data: Record<string, unknown>,
  contract?: RuntimeStatusContract | null,
): RuntimeStatusEvent | null => {
  const statusUpdate = resolveStatusUpdateBody(data);
  if (!statusUpdate) {
    return null;
  }
  const status = statusUpdate.status as { state?: unknown } | undefined;
  if (status && typeof status.state === "string" && status.state.trim()) {
    const metadata =
      statusUpdate.metadata &&
      typeof statusUpdate.metadata === "object" &&
      !Array.isArray(statusUpdate.metadata)
        ? (statusUpdate.metadata as Record<string, unknown>)
        : null;
    const shared =
      metadata?.shared &&
      typeof metadata.shared === "object" &&
      !Array.isArray(metadata.shared)
        ? (metadata.shared as Record<string, unknown>)
        : null;
    const sharedStream =
      shared?.stream &&
      typeof shared.stream === "object" &&
      !Array.isArray(shared.stream)
        ? (shared.stream as Record<string, unknown>)
        : null;
    const rawCompletionPhase =
      typeof sharedStream?.completionPhase === "string"
        ? sharedStream.completionPhase
        : typeof sharedStream?.completion_phase === "string"
          ? sharedStream.completion_phase
          : null;
    const completionPhase =
      rawCompletionPhase?.trim().toLowerCase() === "persisted"
        ? "persisted"
        : null;
    const messageId =
      typeof sharedStream?.messageId === "string" &&
      sharedStream.messageId.trim().length > 0
        ? sharedStream.messageId.trim()
        : typeof sharedStream?.message_id === "string" &&
            sharedStream.message_id.trim().length > 0
          ? sharedStream.message_id.trim()
          : null;
    const resolvedContract = resolveRuntimeStatusContract(contract);
    const state = normalizeRuntimeState(status.state, resolvedContract);
    const isFinal = resolvedContract.terminalStates
      .map((item) => normalizeRuntimeState(item, resolvedContract))
      .includes(state);
    return {
      state,
      isFinal,
      interrupt: extractRuntimeInterrupt(statusUpdate, state, resolvedContract),
      seq:
        pickInteger(sharedStream, ["seq", "sequence"]) ??
        pickInteger(metadata, ["seq"]),
      completionPhase,
      messageId,
    };
  }
  return null;
};

export const extractStreamErrorDetails = (
  data: Record<string, unknown>,
  fallbackMessage = "Stream error.",
): ParsedStreamError => {
  const message =
    pickString(data, ["message", "error"]) ??
    pickRawString(data, ["message", "error"]) ??
    fallbackMessage;
  const upstreamError =
    asRecord(data.upstream_error) ?? asRecord(data.upstreamError);
  const missingParams =
    coerceMissingParams(data.missing_params ?? data.missingParams) ??
    coerceMissingParams(
      resolveNestedValue(upstreamError, ["data", "missing_params"]),
    ) ??
    coerceMissingParams(
      resolveNestedValue(upstreamError, ["data", "missingParams"]),
    );

  return {
    message,
    errorCode: pickString(data, ["error_code", "errorCode"]),
    source: pickString(data, ["source"]),
    jsonrpcCode: pickInt(data, ["jsonrpc_code", "jsonrpcCode"]),
    missingParams,
    upstreamError,
  };
};
