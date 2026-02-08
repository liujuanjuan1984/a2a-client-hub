export type A2AExtensionQueryRequest = {
  page?: number;
  size?: number | null;
  query?: Record<string, unknown> | null;
};

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
