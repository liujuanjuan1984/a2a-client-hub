import type {
  InterruptType,
  PendingRuntimeInterrupt,
  RuntimeStatusContract,
} from "@/lib/api/chat-utils";
import { apiRequest } from "@/lib/api/client";
import { withSharedSessionBinding } from "@/lib/sharedMetadata";

type A2AExtensionResponse = {
  success: boolean;
  result?: Record<string, unknown> | null;
  error_code?: string | null;
  source?: string | null;
  jsonrpc_code?: number | null;
  missing_params?: { name: string; required: boolean }[] | null;
  upstream_error?: Record<string, unknown> | null;
  meta?: Record<string, unknown>;
};

type A2ADeclaredMethodCapability = {
  declared: boolean;
  consumedByHub: boolean;
  method?: string | null;
  availability: "always" | "enabled" | "disabled" | "unsupported";
  configKey?: string | null;
  reason?: string | null;
  retention?: string | null;
};

type A2ADeclaredMethodCollection = {
  declared: boolean;
  consumedByHub: boolean;
  status:
    | "unsupported"
    | "declared_not_consumed"
    | "partially_consumed"
    | "supported"
    | "unsupported_by_design";
  methods: Record<string, A2ADeclaredMethodCapability>;
  declarationSource?:
    | "none"
    | "wire_contract"
    | "wire_contract_fallback"
    | "extension_method_hint"
    | "extension_uri_hint"
    | null;
  declarationConfidence?: "none" | "fallback" | "authoritative" | null;
  negotiationState?: "supported" | "missing" | "invalid" | "unsupported" | null;
  diagnosticNote?: string | null;
};

type A2AExtensionCapabilities = {
  modelSelection: boolean;
  providerDiscovery: boolean;
  interruptRecovery: boolean;
  interruptRecoveryDetails?: {
    declared: boolean;
    consumedByHub: boolean;
    status: "supported" | "unsupported" | "invalid";
    provider?: string | null;
    methods: Record<string, string>;
    recoveryDataSource?: string | null;
    identityScope?: string | null;
    implementationScope?: string | null;
    emptyResultWhenIdentityUnavailable?: boolean | null;
    error?: string | null;
  };
  sessionPromptAsync: boolean;
  sessionControl: {
    append: {
      declared: boolean;
      consumedByHub: boolean;
      status: "supported" | "unsupported";
      routeMode: "unsupported" | "prompt_async" | "turn_steer" | "hybrid";
      requiresStreamIdentity: boolean;
    };
    promptAsync: {
      declared: boolean;
      consumedByHub: boolean;
      availability: "always" | "conditional" | "unsupported";
      method?: string | null;
      enabledByDefault?: boolean | null;
      configKey?: string | null;
    };
    command: {
      declared: boolean;
      consumedByHub: boolean;
      availability: "always" | "conditional" | "unsupported";
      method?: string | null;
      enabledByDefault?: boolean | null;
      configKey?: string | null;
    };
    shell: {
      declared: boolean;
      consumedByHub: boolean;
      availability: "always" | "conditional" | "unsupported";
      method?: string | null;
      enabledByDefault?: boolean | null;
      configKey?: string | null;
    };
  };
  invokeMetadata: {
    declared: boolean;
    consumedByHub: boolean;
    status: "supported" | "unsupported" | "invalid";
    metadataField?: string | null;
    appliesToMethods: string[];
    fields: {
      name: string;
      required: boolean;
      description?: string | null;
    }[];
    error?: string | null;
  };
  requestExecutionOptions?: {
    declared: boolean;
    consumedByHub: boolean;
    status: "supported" | "unsupported" | "declared_not_consumed" | "invalid";
    metadataField?: string | null;
    fields: string[];
    persistsForThread?: boolean | null;
    sourceExtensions: string[];
    notes: string[];
    error?: string | null;
  } | null;
  streamHints?: {
    declared: boolean;
    consumedByHub: boolean;
    status: "supported" | "unsupported" | "invalid";
    streamField?: string | null;
    usageField?: string | null;
    interruptField?: string | null;
    sessionField?: string | null;
    mode?: string | null;
    fallbackUsed?: boolean | null;
    error?: string | null;
  };
  wireContract?: {
    declared: boolean;
    consumedByHub: boolean;
    status: "supported" | "unsupported" | "invalid";
    protocolVersion?: string | null;
    preferredTransport?: string | null;
    additionalTransports: string[];
    allJsonrpcMethods: string[];
    extensionUris: string[];
    conditionalMethods: Record<
      string,
      { reason: string; toggle?: string | null }
    >;
    unsupportedMethodError?: {
      code: number;
      type: string;
      dataFields: string[];
    } | null;
    error?: string | null;
  };
  compatibilityProfile?: {
    declared: boolean;
    status: "supported" | "unsupported" | "invalid";
    uri?: string | null;
    advisoryOnly?: boolean;
    usedFor: string[];
    extensionRetentionCount: number;
    methodRetentionCount: number;
    serviceBehaviorKeys: string[];
    consumerGuidance: string[];
    error?: string | null;
  };
  upstreamMethodFamilies?: {
    discovery: A2ADeclaredMethodCollection;
    threads: A2ADeclaredMethodCollection;
    turns: A2ADeclaredMethodCollection;
    review: A2ADeclaredMethodCollection;
    exec: A2ADeclaredMethodCollection;
  };
  runtimeStatus: RuntimeStatusContract;
};

export class A2AExtensionCallError extends Error {
  errorCode: string | null;
  source: string | null;
  jsonrpcCode: number | null;
  missingParams: { name: string; required: boolean }[] | null;
  upstreamError: Record<string, unknown> | null;

  constructor(
    message: string,
    options?: {
      errorCode?: string | null;
      source?: string | null;
      jsonrpcCode?: number | null;
      missingParams?: { name: string; required: boolean }[] | null;
      upstreamError?: Record<string, unknown> | null;
    },
  ) {
    super(message);
    this.name = "A2AExtensionCallError";
    this.errorCode = options?.errorCode ?? null;
    this.source = options?.source ?? null;
    this.jsonrpcCode = options?.jsonrpcCode ?? null;
    this.missingParams = options?.missingParams ?? null;
    this.upstreamError = options?.upstreamError ?? null;
    Object.setPrototypeOf(this, A2AExtensionCallError.prototype);
  }
}

export const assertExtensionSuccess = (response: A2AExtensionResponse) => {
  if (response.success) return;
  const errorCode =
    typeof response.error_code === "string" ? response.error_code : null;
  const source = typeof response.source === "string" ? response.source : null;
  const jsonrpcCode =
    typeof response.jsonrpc_code === "number" ? response.jsonrpc_code : null;
  const missingParams = Array.isArray(response.missing_params)
    ? response.missing_params.filter(
        (item): item is { name: string; required: boolean } =>
          Boolean(item) &&
          typeof item === "object" &&
          typeof (item as Record<string, unknown>).name === "string",
      )
    : null;
  const upstreamError =
    response.upstream_error && typeof response.upstream_error === "object"
      ? (response.upstream_error as Record<string, unknown>)
      : null;

  const base =
    errorCode === "session_forbidden"
      ? "Session access denied for this operation."
      : errorCode
        ? `Extension call failed (${errorCode})`
        : "Extension call failed";
  throw new A2AExtensionCallError(base, {
    errorCode,
    source,
    jsonrpcCode,
    missingParams,
    upstreamError,
  });
};

export type ExtensionAgentSource = "personal" | "shared";

export type ModelProviderSummary = {
  provider_id: string;
  name?: string;
  source?: string;
  connected?: boolean;
  default_model_id?: string | null;
  model_count?: number | null;
};

export type ModelSummary = {
  provider_id: string;
  model_id: string;
  name?: string;
  status?: string | null;
  context_window?: number | null;
  supports_reasoning?: boolean;
  supports_tool_call?: boolean;
  supports_attachments?: boolean;
  default?: boolean;
  connected?: boolean;
};

type InterruptAckResult = {
  ok: true;
  requestId: string;
};

const buildInterruptPath = (
  source: ExtensionAgentSource,
  agentId: string,
  suffix: string,
) => {
  const base =
    source === "shared"
      ? `/a2a/agents/${encodeURIComponent(agentId)}`
      : `/me/a2a/agents/${encodeURIComponent(agentId)}`;
  return `${base}/extensions/interrupts/${suffix}`;
};

const buildExtensionPath = (
  source: ExtensionAgentSource,
  agentId: string,
  suffix: string,
) => {
  const base =
    source === "shared"
      ? `/a2a/agents/${encodeURIComponent(agentId)}`
      : `/me/a2a/agents/${encodeURIComponent(agentId)}`;
  return `${base}/extensions/${suffix}`;
};

const buildSessionPath = (
  source: ExtensionAgentSource,
  agentId: string,
  suffix: string,
) => {
  const base =
    source === "shared"
      ? `/a2a/agents/${encodeURIComponent(agentId)}`
      : `/me/a2a/agents/${encodeURIComponent(agentId)}`;
  return `${base}/extensions/sessions/${suffix}`;
};

const buildModelDiscoveryPath = (
  source: ExtensionAgentSource,
  agentId: string,
  suffix: "providers:list" | ":list",
) =>
  buildExtensionPath(
    source,
    agentId,
    suffix === "providers:list" ? "models/providers:list" : "models:list",
  );

const assertInterruptAckResult = (
  response: A2AExtensionResponse,
  requestId: string,
): InterruptAckResult => {
  assertExtensionSuccess(response);
  const result =
    response.result && typeof response.result === "object"
      ? (response.result as Record<string, unknown>)
      : {};
  if (result.ok !== true) {
    throw new A2AExtensionCallError(
      "Interrupt callback acknowledged without ok=true",
    );
  }
  return { ok: true, requestId };
};

export const replyPermissionInterrupt = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  requestId: string;
  reply: "once" | "always" | "reject";
  metadata?: Record<string, unknown>;
  workingDirectory?: string | null;
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request_id: string;
      reply: "once" | "always" | "reject";
      metadata?: Record<string, unknown>;
      workingDirectory?: string | null;
    }
  >(buildInterruptPath(input.source, input.agentId, "permission:reply"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      reply: input.reply,
      ...(input.metadata ? { metadata: input.metadata } : {}),
      ...(input.workingDirectory
        ? { workingDirectory: input.workingDirectory }
        : {}),
    },
  });
  return assertInterruptAckResult(response, input.requestId);
};

export const replyQuestionInterrupt = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  requestId: string;
  answers: string[][];
  metadata?: Record<string, unknown>;
  workingDirectory?: string | null;
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request_id: string;
      answers: string[][];
      metadata?: Record<string, unknown>;
      workingDirectory?: string | null;
    }
  >(buildInterruptPath(input.source, input.agentId, "question:reply"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      answers: input.answers,
      ...(input.metadata ? { metadata: input.metadata } : {}),
      ...(input.workingDirectory
        ? { workingDirectory: input.workingDirectory }
        : {}),
    },
  });
  return assertInterruptAckResult(response, input.requestId);
};

export const rejectQuestionInterrupt = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  requestId: string;
  metadata?: Record<string, unknown>;
  workingDirectory?: string | null;
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request_id: string;
      metadata?: Record<string, unknown>;
      workingDirectory?: string | null;
    }
  >(buildInterruptPath(input.source, input.agentId, "question:reject"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      ...(input.metadata ? { metadata: input.metadata } : {}),
      ...(input.workingDirectory
        ? { workingDirectory: input.workingDirectory }
        : {}),
    },
  });
  return assertInterruptAckResult(response, input.requestId);
};

export const replyPermissionsInterrupt = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  requestId: string;
  permissions: Record<string, unknown>;
  scope?: "turn" | "session";
  metadata?: Record<string, unknown>;
  workingDirectory?: string | null;
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request_id: string;
      permissions: Record<string, unknown>;
      scope?: "turn" | "session";
      metadata?: Record<string, unknown>;
      workingDirectory?: string | null;
    }
  >(buildInterruptPath(input.source, input.agentId, "permissions:reply"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      permissions: input.permissions,
      ...(input.scope ? { scope: input.scope } : {}),
      ...(input.metadata ? { metadata: input.metadata } : {}),
      ...(input.workingDirectory
        ? { workingDirectory: input.workingDirectory }
        : {}),
    },
  });
  return assertInterruptAckResult(response, input.requestId);
};

export const replyElicitationInterrupt = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  requestId: string;
  action: "accept" | "decline" | "cancel";
  content?: unknown;
  metadata?: Record<string, unknown>;
  workingDirectory?: string | null;
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request_id: string;
      action: "accept" | "decline" | "cancel";
      content?: unknown;
      metadata?: Record<string, unknown>;
      workingDirectory?: string | null;
    }
  >(buildInterruptPath(input.source, input.agentId, "elicitation:reply"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      action: input.action,
      ...(input.content !== undefined ? { content: input.content } : {}),
      ...(input.metadata ? { metadata: input.metadata } : {}),
      ...(input.workingDirectory
        ? { workingDirectory: input.workingDirectory }
        : {}),
    },
  });
  return assertInterruptAckResult(response, input.requestId);
};

type PromptAsyncAckResult = {
  ok: true;
  sessionId: string;
};

type InterruptRecoveryResponseItem = {
  requestId: string;
  sessionId: string;
  type: InterruptType;
  details?: Record<string, unknown> | null;
  taskId?: string | null;
  contextId?: string | null;
  expiresAt?: number | null;
  source: "recovery";
};

type InterruptRecoveryResult = {
  items: PendingRuntimeInterrupt[];
};

type RecoveryInterruptQuestion = NonNullable<
  PendingRuntimeInterrupt["details"]["questions"]
>[number];
type RecoveryInterruptQuestionOption =
  RecoveryInterruptQuestion["options"][number];

const assertPromptAsyncResult = (
  response: A2AExtensionResponse,
  sessionId: string,
): PromptAsyncAckResult => {
  assertExtensionSuccess(response);
  const result =
    response.result && typeof response.result === "object"
      ? (response.result as Record<string, unknown>)
      : {};
  if (result.ok !== true) {
    throw new A2AExtensionCallError(
      "prompt_async acknowledged without ok=true",
    );
  }
  const resolvedSessionId =
    typeof result.session_id === "string" && result.session_id.trim()
      ? result.session_id.trim()
      : sessionId;
  return {
    ok: true,
    sessionId: resolvedSessionId,
  };
};

const normalizeSessionBindingMetadata = (
  metadata: Record<string, unknown> | undefined,
) => {
  if (!metadata) {
    return undefined;
  }
  const provider =
    typeof metadata.provider === "string" ? metadata.provider.trim() : "";
  const externalSessionId =
    typeof metadata.externalSessionId === "string"
      ? metadata.externalSessionId.trim()
      : "";
  if (!externalSessionId) {
    return metadata;
  }
  return withSharedSessionBinding(metadata, {
    provider: provider || null,
    externalSessionId,
  });
};

export const promptSessionAsync = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  sessionId: string;
  request: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  workingDirectory?: string | null;
}): Promise<PromptAsyncAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request: Record<string, unknown>;
      metadata?: Record<string, unknown>;
      workingDirectory?: string | null;
    }
  >(
    buildSessionPath(
      input.source,
      input.agentId,
      `${encodeURIComponent(input.sessionId)}:prompt-async`,
    ),
    {
      method: "POST",
      body: {
        request: input.request,
        ...(input.metadata
          ? { metadata: normalizeSessionBindingMetadata(input.metadata) }
          : {}),
        ...(input.workingDirectory
          ? { workingDirectory: input.workingDirectory }
          : {}),
      },
    },
  );
  return assertPromptAsyncResult(response, input.sessionId);
};

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const asInterruptQuestions = (
  value: unknown,
): PendingRuntimeInterrupt["details"]["questions"] => {
  if (!Array.isArray(value)) {
    return [];
  }
  const questions: RecoveryInterruptQuestion[] = [];
  value.forEach((item) => {
    const candidate = asRecord(item);
    if (!candidate || typeof candidate.question !== "string") {
      return;
    }

    const options: RecoveryInterruptQuestionOption[] = [];
    if (Array.isArray(candidate.options)) {
      candidate.options.forEach((option) => {
        const resolved = asRecord(option);
        if (!resolved || typeof resolved.label !== "string") {
          return;
        }
        options.push({
          label: resolved.label,
          description:
            typeof resolved.description === "string"
              ? resolved.description
              : null,
          value: typeof resolved.value === "string" ? resolved.value : null,
        });
      });
    }

    questions.push({
      header: typeof candidate.header === "string" ? candidate.header : null,
      description:
        typeof candidate.description === "string"
          ? candidate.description
          : null,
      question: candidate.question,
      options,
    });
  });
  return questions;
};

const asRecoveryInterruptItem = (
  value: unknown,
): PendingRuntimeInterrupt | null => {
  const item = asRecord(value);
  if (!item) {
    return null;
  }
  const requestId =
    typeof item.requestId === "string" ? item.requestId.trim() : "";
  const sessionId =
    typeof item.sessionId === "string" ? item.sessionId.trim() : "";
  const interruptType = item.type;
  if (
    !requestId ||
    !sessionId ||
    (interruptType !== "permission" &&
      interruptType !== "question" &&
      interruptType !== "permissions" &&
      interruptType !== "elicitation")
  ) {
    return null;
  }

  const details = asRecord(item.details) ?? {};
  const base: Omit<PendingRuntimeInterrupt, "details"> = {
    requestId,
    sessionId,
    type: interruptType,
    phase: "asked",
    source: "recovery",
    taskId: typeof item.taskId === "string" ? item.taskId : null,
    contextId: typeof item.contextId === "string" ? item.contextId : null,
    expiresAt: typeof item.expiresAt === "number" ? item.expiresAt : null,
  };

  if (interruptType === "permission") {
    return {
      ...base,
      details: {
        ...details,
        permission:
          typeof details.permission === "string" ? details.permission : null,
        patterns: Array.isArray(details.patterns)
          ? details.patterns.filter(
              (pattern): pattern is string =>
                typeof pattern === "string" && pattern.trim().length > 0,
            )
          : [],
        displayMessage:
          typeof details.displayMessage === "string"
            ? details.displayMessage
            : typeof details.display_message === "string"
              ? details.display_message
              : null,
      },
    };
  }

  if (interruptType === "permissions") {
    return {
      ...base,
      details: {
        permissions: asRecord(details.permissions),
        displayMessage:
          typeof details.displayMessage === "string"
            ? details.displayMessage
            : typeof details.display_message === "string"
              ? details.display_message
              : null,
      },
    };
  }

  if (interruptType === "elicitation") {
    const meta = asRecord(details.meta);
    return {
      ...base,
      details: {
        displayMessage:
          typeof details.displayMessage === "string"
            ? details.displayMessage
            : typeof details.display_message === "string"
              ? details.display_message
              : null,
        serverName:
          typeof details.serverName === "string"
            ? details.serverName
            : typeof details.server_name === "string"
              ? details.server_name
              : null,
        mode: typeof details.mode === "string" ? details.mode : null,
        requestedSchema:
          details.requestedSchema ?? details.requested_schema ?? null,
        url: typeof details.url === "string" ? details.url : null,
        elicitationId:
          typeof details.elicitationId === "string"
            ? details.elicitationId
            : typeof details.elicitation_id === "string"
              ? details.elicitation_id
              : null,
        ...(meta ? { meta } : {}),
      },
    };
  }

  return {
    ...base,
    details: {
      ...details,
      displayMessage:
        typeof details.displayMessage === "string"
          ? details.displayMessage
          : typeof details.display_message === "string"
            ? details.display_message
            : null,
      questions: asInterruptQuestions(details.questions),
    },
  };
};

const asProviderItems = (value: unknown): ModelProviderSummary[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is ModelProviderSummary =>
      Boolean(item) &&
      typeof item === "object" &&
      typeof (item as Record<string, unknown>).provider_id === "string",
  );
};

const asModelItems = (value: unknown): ModelSummary[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is ModelSummary =>
      Boolean(item) &&
      typeof item === "object" &&
      typeof (item as Record<string, unknown>).provider_id === "string" &&
      typeof (item as Record<string, unknown>).model_id === "string",
  );
};

export const getExtensionCapabilities = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
}): Promise<A2AExtensionCapabilities> => {
  const response = await apiRequest<A2AExtensionCapabilities>(
    buildExtensionPath(input.source, input.agentId, "capabilities"),
    {
      method: "GET",
    },
  );
  return response;
};

export const recoverInterrupts = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  sessionId?: string | null;
}): Promise<InterruptRecoveryResult> => {
  const response = await apiRequest<
    { items?: InterruptRecoveryResponseItem[] },
    { sessionId?: string }
  >(buildExtensionPath(input.source, input.agentId, "interrupts:recover"), {
    method: "POST",
    body: input.sessionId?.trim() ? { sessionId: input.sessionId.trim() } : {},
  });
  return {
    items: Array.isArray(response.items)
      ? response.items
          .map((item) => asRecoveryInterruptItem(item))
          .filter((item): item is PendingRuntimeInterrupt => Boolean(item))
      : [],
  };
};

export const listModelProviders = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  workingDirectory?: string | null;
}) => {
  const response = await apiRequest<
    A2AExtensionResponse,
    { workingDirectory?: string }
  >(buildModelDiscoveryPath(input.source, input.agentId, "providers:list"), {
    method: "POST",
    body: input.workingDirectory?.trim()
      ? { workingDirectory: input.workingDirectory.trim() }
      : {},
  });
  assertExtensionSuccess(response);
  const result = asRecord(response.result) ?? {};
  return {
    items: asProviderItems(result.items),
    defaultByProvider: asRecord(result.default_by_provider) ?? {},
    connected: Array.isArray(result.connected)
      ? result.connected.filter(
          (item): item is string =>
            typeof item === "string" && item.trim().length > 0,
        )
      : [],
  };
};

export const listModels = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  providerId?: string;
  workingDirectory?: string | null;
}) => {
  const body: {
    provider_id?: string;
    workingDirectory?: string;
  } = {};
  if (input.providerId?.trim()) {
    body.provider_id = input.providerId.trim();
  }
  if (input.workingDirectory?.trim()) {
    body.workingDirectory = input.workingDirectory.trim();
  }
  const response = await apiRequest<
    A2AExtensionResponse,
    { provider_id?: string; workingDirectory?: string }
  >(buildModelDiscoveryPath(input.source, input.agentId, ":list"), {
    method: "POST",
    body,
  });
  assertExtensionSuccess(response);
  const result = asRecord(response.result) ?? {};
  return {
    items: asModelItems(result.items),
    defaultByProvider: asRecord(result.default_by_provider) ?? {},
    connected: Array.isArray(result.connected)
      ? result.connected.filter(
          (item): item is string =>
            typeof item === "string" && item.trim().length > 0,
        )
      : [],
  };
};
