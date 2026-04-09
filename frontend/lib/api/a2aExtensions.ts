import type {
  InterruptType,
  PendingRuntimeInterrupt,
  RuntimeStatusContract,
} from "@/lib/api/chat-utils";
import { apiRequest } from "@/lib/api/client";

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

type DeclaredMethodCapability = {
  declared: boolean;
  consumedByHub: boolean;
  method?: string | null;
  availability?: "always" | "enabled" | "disabled" | "unsupported";
  configKey?: string | null;
  reason?: string | null;
  retention?: string | null;
};

type DeclaredMethodCollectionCapability<MethodKey extends string> = {
  declared: boolean;
  consumedByHub: boolean;
  status:
    | "unsupported"
    | "declared_not_consumed"
    | "partially_consumed"
    | "supported"
    | "unsupported_by_design";
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
  methods: Partial<Record<MethodKey, DeclaredMethodCapability>>;
};

type DiscoveryMethodCollectionCapability<MethodKey extends string> = Omit<
  DeclaredMethodCollectionCapability<MethodKey>,
  "status"
> & {
  status:
    | "unsupported"
    | "declared_not_consumed"
    | "partially_consumed"
    | "supported";
};

type A2AExtensionCapabilities = {
  modelSelection: boolean;
  providerDiscovery: boolean;
  interruptRecovery: boolean;
  sessionPromptAsync: boolean;
  sessionControl: {
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
    status: "unsupported" | "declared_not_consumed" | "invalid";
    metadataField?: string | null;
    fields: string[];
    persistsForThread?: boolean | null;
    sourceExtensions: string[];
    notes: string[];
    error?: string | null;
  } | null;
  runtimeStatus: RuntimeStatusContract;
  codexDiscovery?: DiscoveryMethodCollectionCapability<
    "skillsList" | "appsList" | "pluginsList" | "pluginsRead" | "watch"
  > | null;
  codexThreads?: DeclaredMethodCollectionCapability<
    "fork" | "archive" | "unarchive" | "metadataUpdate" | "watch"
  > | null;
  codexTurns?: DeclaredMethodCollectionCapability<"steer"> | null;
  codexReview?: DeclaredMethodCollectionCapability<"start" | "watch"> | null;
  codexExec?: DeclaredMethodCollectionCapability<
    "start" | "write" | "resize" | "terminate"
  > | null;
  codexThreadWatch?: DeclaredMethodCapability & {
    status?: "unsupported" | "unsupported_by_design";
  };
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

type ExtensionAgentSource = "personal" | "shared";

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

export type CodexDiscoveryStatus =
  | "unknown"
  | "unsupported"
  | "declared_not_consumed"
  | "partially_consumed"
  | "supported";

export type CodexDiscoveryListKind = "skills" | "apps" | "plugins";

type CodexDiscoverySkill = {
  name: string;
  path: string;
  description: string;
  enabled: boolean;
  scope: string;
  interface: Record<string, unknown> | null;
  codex: Record<string, unknown>;
};

type CodexDiscoverySkillScope = {
  cwd: string;
  skills: CodexDiscoverySkill[];
  errors: Record<string, unknown>[];
  codex: Record<string, unknown>;
};

type CodexDiscoveryApp = {
  id: string;
  name: string;
  description: string | null;
  isAccessible: boolean;
  isEnabled: boolean;
  installUrl: string | null;
  mentionPath: string;
  branding: Record<string, unknown> | null;
  labels: Record<string, unknown>[];
  codex: Record<string, unknown>;
};

type CodexDiscoveryPluginSummary = {
  name: string;
  description: string | null;
  enabled: boolean | null;
  interface: Record<string, unknown> | null;
  mentionPath: string;
  codex: Record<string, unknown>;
};

type CodexDiscoveryPluginMarketplace = {
  marketplaceName: string;
  marketplacePath: string;
  interface: Record<string, unknown> | null;
  plugins: CodexDiscoveryPluginSummary[];
  codex: Record<string, unknown>;
};

export type CodexDiscoveryPluginDetail = {
  name: string;
  marketplaceName: string;
  marketplacePath: string;
  mentionPath: string;
  summary: string[];
  skills: Record<string, unknown>[];
  apps: Record<string, unknown>[];
  mcpServers: string[];
  interface: Record<string, unknown> | null;
  codex: Record<string, unknown>;
};

export type CodexDiscoverySkillsListResult = {
  items: CodexDiscoverySkillScope[];
};

export type CodexDiscoveryAppsListResult = {
  items: CodexDiscoveryApp[];
  nextCursor: string | null;
};

export type CodexDiscoveryPluginsListResult = {
  items: CodexDiscoveryPluginMarketplace[];
  featuredPluginIds: string[];
  marketplaceLoadErrors: Record<string, unknown>[];
  remoteSyncError: string | null;
};

type CodexDiscoveryListResult =
  | CodexDiscoverySkillsListResult
  | CodexDiscoveryAppsListResult
  | CodexDiscoveryPluginsListResult;

type CodexDiscoveryPluginReadResult = {
  item: CodexDiscoveryPluginDetail | null;
};

export type CodexDiscoveryListEntry = {
  id: string;
  kind: "skill" | "app" | "plugin";
  title: string;
  description: string | null;
  subtitle: string | null;
  badge: string | null;
  pluginRef?: {
    marketplacePath: string;
    pluginName: string;
  } | null;
};

export type CodexDiscoveryCapability = NonNullable<
  A2AExtensionCapabilities["codexDiscovery"]
>;
export type CodexThreadsCapability = NonNullable<
  A2AExtensionCapabilities["codexThreads"]
>;
export type CodexTurnsCapability = NonNullable<
  A2AExtensionCapabilities["codexTurns"]
>;
export type CodexReviewCapability = NonNullable<
  A2AExtensionCapabilities["codexReview"]
>;
export type CodexExecCapability = NonNullable<
  A2AExtensionCapabilities["codexExec"]
>;
export type RequestExecutionOptionsCapability = NonNullable<
  A2AExtensionCapabilities["requestExecutionOptions"]
>;

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

const buildCodexDiscoveryPath = (
  source: ExtensionAgentSource,
  agentId: string,
  suffix:
    | "codex/skills"
    | "codex/apps"
    | "codex/plugins"
    | "codex/plugins:read",
) => buildExtensionPath(source, agentId, suffix);

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
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request_id: string;
      reply: "once" | "always" | "reject";
      metadata?: Record<string, unknown>;
    }
  >(buildInterruptPath(input.source, input.agentId, "permission:reply"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      reply: input.reply,
      ...(input.metadata ? { metadata: input.metadata } : {}),
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
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request_id: string;
      answers: string[][];
      metadata?: Record<string, unknown>;
    }
  >(buildInterruptPath(input.source, input.agentId, "question:reply"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      answers: input.answers,
      ...(input.metadata ? { metadata: input.metadata } : {}),
    },
  });
  return assertInterruptAckResult(response, input.requestId);
};

export const rejectQuestionInterrupt = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  requestId: string;
  metadata?: Record<string, unknown>;
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    { request_id: string; metadata?: Record<string, unknown> }
  >(buildInterruptPath(input.source, input.agentId, "question:reject"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      ...(input.metadata ? { metadata: input.metadata } : {}),
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
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request_id: string;
      permissions: Record<string, unknown>;
      scope?: "turn" | "session";
      metadata?: Record<string, unknown>;
    }
  >(buildInterruptPath(input.source, input.agentId, "permissions:reply"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      permissions: input.permissions,
      ...(input.scope ? { scope: input.scope } : {}),
      ...(input.metadata ? { metadata: input.metadata } : {}),
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
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request_id: string;
      action: "accept" | "decline" | "cancel";
      content?: unknown;
      metadata?: Record<string, unknown>;
    }
  >(buildInterruptPath(input.source, input.agentId, "elicitation:reply"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      action: input.action,
      ...(input.content !== undefined ? { content: input.content } : {}),
      ...(input.metadata ? { metadata: input.metadata } : {}),
    },
  });
  return assertInterruptAckResult(response, input.requestId);
};

type PromptAsyncAckResult = {
  ok: true;
  sessionId: string;
};

type SessionCommandResultItem = {
  kind?: string;
  messageId?: string;
  message_id?: string;
  role?: string;
  parts?: unknown[];
  createdAt?: string;
  created_at?: string;
};

type SessionCommandResult = {
  item: SessionCommandResultItem | null;
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

export const promptSessionAsync = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  sessionId: string;
  request: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}): Promise<PromptAsyncAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request: Record<string, unknown>;
      metadata?: Record<string, unknown>;
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
        ...(input.metadata ? { metadata: input.metadata } : {}),
      },
    },
  );
  return assertPromptAsyncResult(response, input.sessionId);
};

export const commandSession = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  sessionId: string;
  request: {
    command: string;
    arguments: string;
    parts?: Record<string, unknown>[];
  };
  metadata?: Record<string, unknown>;
}): Promise<SessionCommandResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      request: {
        command: string;
        arguments: string;
        parts?: Record<string, unknown>[];
      };
      metadata?: Record<string, unknown>;
    }
  >(
    buildSessionPath(
      input.source,
      input.agentId,
      `${encodeURIComponent(input.sessionId)}:command`,
    ),
    {
      method: "POST",
      body: {
        request: input.request,
        ...(input.metadata ? { metadata: input.metadata } : {}),
      },
    },
  );
  assertExtensionSuccess(response);
  const result = asRecord(response.result) ?? {};
  const item = asRecord(result.item);
  return {
    item: item ? (item as SessionCommandResultItem) : null,
  };
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

const asStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is string =>
      typeof item === "string" && item.trim().length > 0,
  );
};

const asRecordArray = (value: unknown): Record<string, unknown>[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item));
};

const asCodexEnvelope = (value: unknown): Record<string, unknown> =>
  asRecord(value) ?? {};

const asCodexDiscoverySkill = (value: unknown): CodexDiscoverySkill | null => {
  const item = asRecord(value);
  if (
    !item ||
    typeof item.name !== "string" ||
    typeof item.path !== "string" ||
    typeof item.description !== "string" ||
    typeof item.enabled !== "boolean" ||
    typeof item.scope !== "string"
  ) {
    return null;
  }
  return {
    name: item.name,
    path: item.path,
    description: item.description,
    enabled: item.enabled,
    scope: item.scope,
    interface: asRecord(item.interface),
    codex: asCodexEnvelope(item.codex),
  };
};

const asCodexDiscoverySkillScope = (
  value: unknown,
): CodexDiscoverySkillScope | null => {
  const item = asRecord(value);
  if (!item || typeof item.cwd !== "string") {
    return null;
  }
  return {
    cwd: item.cwd,
    skills: Array.isArray(item.skills)
      ? item.skills
          .map((skill) => asCodexDiscoverySkill(skill))
          .filter((skill): skill is CodexDiscoverySkill => Boolean(skill))
      : [],
    errors: asRecordArray(item.errors),
    codex: asCodexEnvelope(item.codex),
  };
};

const asCodexDiscoveryApp = (value: unknown): CodexDiscoveryApp | null => {
  const item = asRecord(value);
  if (
    !item ||
    typeof item.id !== "string" ||
    typeof item.name !== "string" ||
    typeof item.mentionPath !== "string"
  ) {
    return null;
  }
  return {
    id: item.id,
    name: item.name,
    description: typeof item.description === "string" ? item.description : null,
    isAccessible: item.isAccessible === true,
    isEnabled: item.isEnabled === true,
    installUrl: typeof item.installUrl === "string" ? item.installUrl : null,
    mentionPath: item.mentionPath,
    branding: asRecord(item.branding),
    labels: asRecordArray(item.labels),
    codex: asCodexEnvelope(item.codex),
  };
};

const asCodexDiscoveryPluginSummary = (
  value: unknown,
): CodexDiscoveryPluginSummary | null => {
  const item = asRecord(value);
  if (
    !item ||
    typeof item.name !== "string" ||
    typeof item.mentionPath !== "string"
  ) {
    return null;
  }
  return {
    name: item.name,
    description: typeof item.description === "string" ? item.description : null,
    enabled: typeof item.enabled === "boolean" ? item.enabled : null,
    interface: asRecord(item.interface),
    mentionPath: item.mentionPath,
    codex: asCodexEnvelope(item.codex),
  };
};

const asCodexDiscoveryPluginMarketplace = (
  value: unknown,
): CodexDiscoveryPluginMarketplace | null => {
  const item = asRecord(value);
  if (
    !item ||
    typeof item.marketplaceName !== "string" ||
    typeof item.marketplacePath !== "string"
  ) {
    return null;
  }
  return {
    marketplaceName: item.marketplaceName,
    marketplacePath: item.marketplacePath,
    interface: asRecord(item.interface),
    plugins: Array.isArray(item.plugins)
      ? item.plugins
          .map((plugin) => asCodexDiscoveryPluginSummary(plugin))
          .filter((plugin): plugin is CodexDiscoveryPluginSummary =>
            Boolean(plugin),
          )
      : [],
    codex: asCodexEnvelope(item.codex),
  };
};

const asCodexDiscoveryPluginDetail = (
  value: unknown,
): CodexDiscoveryPluginDetail | null => {
  const item = asRecord(value);
  if (
    !item ||
    typeof item.name !== "string" ||
    typeof item.marketplacePath !== "string" ||
    typeof item.marketplaceName !== "string" ||
    typeof item.mentionPath !== "string"
  ) {
    return null;
  }
  return {
    name: item.name,
    marketplaceName: item.marketplaceName,
    marketplacePath: item.marketplacePath,
    mentionPath: item.mentionPath,
    summary: asStringArray(item.summary),
    skills: asRecordArray(item.skills),
    apps: asRecordArray(item.apps),
    mcpServers: asStringArray(item.mcpServers),
    interface: asRecord(item.interface),
    codex: asCodexEnvelope(item.codex),
  };
};

export const toCodexDiscoveryEntries = (
  kind: CodexDiscoveryListKind,
  result: CodexDiscoveryListResult | null | undefined,
): CodexDiscoveryListEntry[] => {
  if (!result) {
    return [];
  }
  if (kind === "skills") {
    return result.items.flatMap((scope) =>
      "cwd" in scope
        ? scope.skills.map((skill) => ({
            id: skill.path,
            kind: "skill" as const,
            title: skill.name,
            description: skill.description,
            subtitle: scope.cwd,
            badge: skill.scope,
            pluginRef: null,
          }))
        : [],
    );
  }
  if (kind === "apps") {
    return result.items.flatMap((app) =>
      "mentionPath" in app
        ? [
            {
              id: app.id,
              kind: "app" as const,
              title: app.name,
              description: app.description,
              subtitle: app.mentionPath,
              badge: app.isEnabled ? "enabled" : "disabled",
              pluginRef: null,
            },
          ]
        : [],
    );
  }
  return result.items.flatMap((marketplace) =>
    "marketplacePath" in marketplace
      ? marketplace.plugins.map((plugin) => ({
          id: `${marketplace.marketplacePath}:${plugin.name}`,
          kind: "plugin" as const,
          title: plugin.name,
          description: plugin.description,
          subtitle: marketplace.marketplaceName,
          badge: plugin.enabled === true ? "enabled" : null,
          pluginRef: {
            marketplacePath: marketplace.marketplacePath,
            pluginName: plugin.name,
          },
        }))
      : [],
  );
};

const listCodexSkillsRequest = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
}): Promise<CodexDiscoverySkillsListResult> => {
  const response = await apiRequest<A2AExtensionResponse>(
    buildCodexDiscoveryPath(input.source, input.agentId, "codex/skills"),
    {
      method: "GET",
    },
  );
  assertExtensionSuccess(response);
  const result = asRecord(response.result) ?? {};
  return {
    items: Array.isArray(result.items)
      ? result.items
          .map((item) => asCodexDiscoverySkillScope(item))
          .filter((item): item is CodexDiscoverySkillScope => Boolean(item))
      : [],
  };
};

const listCodexAppsRequest = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
}): Promise<CodexDiscoveryAppsListResult> => {
  const response = await apiRequest<A2AExtensionResponse>(
    buildCodexDiscoveryPath(input.source, input.agentId, "codex/apps"),
    {
      method: "GET",
    },
  );
  assertExtensionSuccess(response);
  const result = asRecord(response.result) ?? {};
  return {
    items: Array.isArray(result.items)
      ? result.items
          .map((item) => asCodexDiscoveryApp(item))
          .filter((item): item is CodexDiscoveryApp => Boolean(item))
      : [],
    nextCursor:
      typeof result.nextCursor === "string" ? result.nextCursor : null,
  };
};

const listCodexPluginsRequest = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
}): Promise<CodexDiscoveryPluginsListResult> => {
  const response = await apiRequest<A2AExtensionResponse>(
    buildCodexDiscoveryPath(input.source, input.agentId, "codex/plugins"),
    {
      method: "GET",
    },
  );
  assertExtensionSuccess(response);
  const result = asRecord(response.result) ?? {};
  return {
    items: Array.isArray(result.items)
      ? result.items
          .map((item) => asCodexDiscoveryPluginMarketplace(item))
          .filter((item): item is CodexDiscoveryPluginMarketplace =>
            Boolean(item),
          )
      : [],
    featuredPluginIds: asStringArray(result.featuredPluginIds),
    marketplaceLoadErrors: asRecordArray(result.marketplaceLoadErrors),
    remoteSyncError:
      typeof result.remoteSyncError === "string"
        ? result.remoteSyncError
        : null,
  };
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
  sessionMetadata?: Record<string, unknown>;
}) => {
  const response = await apiRequest<
    A2AExtensionResponse,
    { session_metadata?: Record<string, unknown> }
  >(buildModelDiscoveryPath(input.source, input.agentId, "providers:list"), {
    method: "POST",
    body: input.sessionMetadata
      ? { session_metadata: input.sessionMetadata }
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
  sessionMetadata?: Record<string, unknown>;
}) => {
  const body: {
    provider_id?: string;
    session_metadata?: Record<string, unknown>;
  } = {};
  if (input.providerId?.trim()) {
    body.provider_id = input.providerId.trim();
  }
  if (input.sessionMetadata) {
    body.session_metadata = input.sessionMetadata;
  }
  const response = await apiRequest<
    A2AExtensionResponse,
    { provider_id?: string; session_metadata?: Record<string, unknown> }
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

export const listCodexSkills = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
}) => await listCodexSkillsRequest(input);

export const listCodexApps = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
}) => await listCodexAppsRequest(input);

export const listCodexPlugins = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
}) => await listCodexPluginsRequest(input);

export const readCodexPlugin = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  marketplacePath: string;
  pluginName: string;
}): Promise<CodexDiscoveryPluginReadResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    {
      marketplacePath: string;
      pluginName: string;
    }
  >(
    buildCodexDiscoveryPath(input.source, input.agentId, "codex/plugins:read"),
    {
      method: "POST",
      body: {
        marketplacePath: input.marketplacePath.trim(),
        pluginName: input.pluginName.trim(),
      },
    },
  );
  assertExtensionSuccess(response);
  const result = asRecord(response.result) ?? {};
  return {
    item: asCodexDiscoveryPluginDetail(result.item),
  };
};
