import type { RuntimeStatusContract } from "@/lib/api/chat-utils";
import { apiRequest } from "@/lib/api/client";

export type A2AExtensionResponse = {
  success: boolean;
  result?: Record<string, unknown> | null;
  error_code?: string | null;
  source?: string | null;
  jsonrpc_code?: number | null;
  missing_params?: { name: string; required: boolean }[] | null;
  upstream_error?: Record<string, unknown> | null;
  meta?: Record<string, unknown>;
};

export type A2AExtensionCapabilities = {
  modelSelection: boolean;
  providerDiscovery: boolean;
  sessionPromptAsync: boolean;
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

type PromptAsyncAckResult = {
  ok: true;
  sessionId: string;
};

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

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

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
