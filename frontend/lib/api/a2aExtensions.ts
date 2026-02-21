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

  const base = errorCode
    ? `Extension call failed (${errorCode})`
    : "Extension call failed";
  throw new A2AExtensionCallError(base, { errorCode, upstreamError });
};

type InterruptAgentSource = "personal" | "shared";

type InterruptAckResult = {
  ok: true;
  requestId: string;
};

const buildOpencodeInterruptPath = (
  source: InterruptAgentSource,
  agentId: string,
  suffix: string,
) => {
  const base =
    source === "shared"
      ? `/a2a/agents/${encodeURIComponent(agentId)}`
      : `/me/a2a/agents/${encodeURIComponent(agentId)}`;
  return `${base}/extensions/opencode/interrupts/${suffix}`;
};

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

export const replyOpencodePermissionInterrupt = async (input: {
  source: InterruptAgentSource;
  agentId: string;
  requestId: string;
  reply: "once" | "always" | "reject";
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    { request_id: string; reply: "once" | "always" | "reject" }
  >(
    buildOpencodeInterruptPath(input.source, input.agentId, "permission:reply"),
    {
      method: "POST",
      body: {
        request_id: input.requestId,
        reply: input.reply,
      },
    },
  );
  return assertInterruptAckResult(response, input.requestId);
};

export const replyOpencodeQuestionInterrupt = async (input: {
  source: InterruptAgentSource;
  agentId: string;
  requestId: string;
  answers: string[][];
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    { request_id: string; answers: string[][] }
  >(buildOpencodeInterruptPath(input.source, input.agentId, "question:reply"), {
    method: "POST",
    body: {
      request_id: input.requestId,
      answers: input.answers,
    },
  });
  return assertInterruptAckResult(response, input.requestId);
};

export const rejectOpencodeQuestionInterrupt = async (input: {
  source: InterruptAgentSource;
  agentId: string;
  requestId: string;
}): Promise<InterruptAckResult> => {
  const response = await apiRequest<
    A2AExtensionResponse,
    { request_id: string }
  >(
    buildOpencodeInterruptPath(input.source, input.agentId, "question:reject"),
    {
      method: "POST",
      body: {
        request_id: input.requestId,
      },
    },
  );
  return assertInterruptAckResult(response, input.requestId);
};
