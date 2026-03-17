import { apiRequest } from "@/lib/api/client";

export type A2AExtensionResponse = {
  success: boolean;
  result?: Record<string, unknown> | null;
  error_code?: string | null;
  upstream_error?: Record<string, unknown> | null;
  meta?: Record<string, unknown>;
};

export class A2AExtensionCallError extends Error {
  errorCode: string | null;
  upstreamError: Record<string, unknown> | null;

  constructor(
    message: string,
    options?: {
      errorCode?: string | null;
      upstreamError?: Record<string, unknown> | null;
    },
  ) {
    super(message);
    this.name = "A2AExtensionCallError";
    this.errorCode = options?.errorCode ?? null;
    this.upstreamError = options?.upstreamError ?? null;
    Object.setPrototypeOf(this, A2AExtensionCallError.prototype);
  }
}

export const assertExtensionSuccess = (response: A2AExtensionResponse) => {
  if (response.success) return;
  const errorCode =
    typeof response.error_code === "string" ? response.error_code : null;
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
  throw new A2AExtensionCallError(base, { errorCode, upstreamError });
};

type ExtensionAgentSource = "personal" | "shared";

export type OpencodeProviderSummary = {
  provider_id: string;
  name?: string;
  source?: string;
  connected?: boolean;
  default_model_id?: string | null;
  model_count?: number | null;
};

export type OpencodeModelSummary = {
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

const buildOpencodeDiscoveryPath = (
  source: ExtensionAgentSource,
  agentId: string,
  suffix: string,
) => buildExtensionPath(source, agentId, `opencode/${suffix}`);

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

const asProviderItems = (value: unknown): OpencodeProviderSummary[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is OpencodeProviderSummary =>
      Boolean(item) &&
      typeof item === "object" &&
      typeof (item as Record<string, unknown>).provider_id === "string",
  );
};

const asModelItems = (value: unknown): OpencodeModelSummary[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is OpencodeModelSummary =>
      Boolean(item) &&
      typeof item === "object" &&
      typeof (item as Record<string, unknown>).provider_id === "string" &&
      typeof (item as Record<string, unknown>).model_id === "string",
  );
};

export const getExtensionCapabilities = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
}): Promise<{ modelSelection: boolean }> => {
  const response = await apiRequest<{ modelSelection: boolean }>(
    buildExtensionPath(input.source, input.agentId, "capabilities"),
    {
      method: "GET",
    },
  );
  return response;
};

export const listOpencodeProviders = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  metadata?: Record<string, unknown>;
}) => {
  const response = await apiRequest<
    A2AExtensionResponse,
    { metadata?: Record<string, unknown> }
  >(buildOpencodeDiscoveryPath(input.source, input.agentId, "providers:list"), {
    method: "POST",
    body: input.metadata ? { metadata: input.metadata } : {},
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

export const listOpencodeModels = async (input: {
  source: ExtensionAgentSource;
  agentId: string;
  providerId?: string;
  metadata?: Record<string, unknown>;
}) => {
  const body: { provider_id?: string; metadata?: Record<string, unknown> } = {};
  if (input.providerId?.trim()) {
    body.provider_id = input.providerId.trim();
  }
  if (input.metadata) {
    body.metadata = input.metadata;
  }
  const response = await apiRequest<
    A2AExtensionResponse,
    { provider_id?: string; metadata?: Record<string, unknown> }
  >(buildOpencodeDiscoveryPath(input.source, input.agentId, "models:list"), {
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
