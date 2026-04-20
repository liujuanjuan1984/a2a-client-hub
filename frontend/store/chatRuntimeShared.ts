import {
  type PendingRuntimeInterrupt,
  type StreamErrorDetails,
  type StreamMissingParam,
} from "@/lib/api/chat-utils";
import { ApiRequestError } from "@/lib/api/client";
import { type ResolvedRuntimeInterruptRecord } from "@/lib/chat-utils";

export const isSamePendingInterrupt = (
  left: PendingRuntimeInterrupt | null | undefined,
  right: PendingRuntimeInterrupt | null | undefined,
) => {
  const lhs = left ?? null;
  const rhs = right ?? null;
  if (lhs === rhs) return true;
  if (!lhs || !rhs) return false;
  if (lhs.requestId !== rhs.requestId || lhs.type !== rhs.type) {
    return false;
  }
  return (
    JSON.stringify(lhs.details ?? {}) === JSON.stringify(rhs.details ?? {})
  );
};

export const isSameResolvedInterrupt = (
  left: ResolvedRuntimeInterruptRecord | null | undefined,
  right: ResolvedRuntimeInterruptRecord | null | undefined,
) => {
  const lhs = left ?? null;
  const rhs = right ?? null;
  if (lhs === rhs) return true;
  if (!lhs || !rhs) return false;
  return (
    lhs.requestId === rhs.requestId &&
    lhs.type === rhs.type &&
    lhs.phase === rhs.phase &&
    lhs.resolution === rhs.resolution
  );
};

export const arePendingInterruptQueuesEqual = (
  left: PendingRuntimeInterrupt[],
  right: PendingRuntimeInterrupt[],
) => {
  if (left === right) {
    return true;
  }
  if (left.length !== right.length) {
    return false;
  }
  return left.every((item, index) =>
    isSamePendingInterrupt(item, right[index]),
  );
};

export const buildApiErrorMessage = (error: unknown): string => {
  if (!(error instanceof ApiRequestError)) {
    return error instanceof Error ? error.message : "Request failed.";
  }

  const codeSuffix =
    error.errorCode && !error.message.includes(`[${error.errorCode}]`)
      ? ` [${error.errorCode}]`
      : "";
  const upstreamMessage =
    error.upstreamError &&
    typeof error.upstreamError === "object" &&
    typeof error.upstreamError.message === "string"
      ? error.upstreamError.message
      : null;

  return upstreamMessage
    ? `${error.message}${codeSuffix}：${upstreamMessage}`
    : `${error.message}${codeSuffix}`;
};

export const normalizeErrorCode = (value: unknown): string | null =>
  typeof value === "string" && value.trim().length > 0 ? value.trim() : null;

const formatMissingParamLabel = (
  missingParams: StreamMissingParam[] | null | undefined,
) => {
  if (!missingParams?.length) {
    return null;
  }
  return missingParams.map((item) => item.name).join(", ");
};

const extractUpstreamErrorMessage = (
  upstreamError: Record<string, unknown> | null | undefined,
) => {
  if (!upstreamError) {
    return null;
  }
  const message = upstreamError.message;
  return typeof message === "string" && message.trim().length > 0
    ? message.trim()
    : null;
};

export const buildStreamErrorMessage = ({
  errorText,
  details,
}: {
  errorText: string;
  details?: Partial<StreamErrorDetails>;
}) => {
  const missingParams = formatMissingParamLabel(details?.missingParams);
  if (missingParams) {
    return `Missing required upstream parameters: ${missingParams}`;
  }
  const upstreamMessage = extractUpstreamErrorMessage(details?.upstreamError);
  if (
    upstreamMessage &&
    ["Upstream streaming failed", "Stream error."].includes(errorText.trim())
  ) {
    return upstreamMessage;
  }
  return errorText;
};

export const buildApiErrorDetails = (
  error: unknown,
): {
  message: string;
  errorCode: string | null;
  source: string | null;
  jsonrpcCode: number | null;
  missingParams: { name: string; required: boolean }[] | null;
  upstreamError: Record<string, unknown> | null;
} => ({
  message: buildApiErrorMessage(error),
  errorCode:
    error instanceof ApiRequestError
      ? normalizeErrorCode(error.errorCode)
      : null,
  source: error instanceof ApiRequestError ? error.source : null,
  jsonrpcCode: error instanceof ApiRequestError ? error.jsonrpcCode : null,
  missingParams: error instanceof ApiRequestError ? error.missingParams : null,
  upstreamError: error instanceof ApiRequestError ? error.upstreamError : null,
});

const streamWarnThrottleMs = 15_000;
const streamWarnTimestamps = new Map<string, number>();

export const warnStreamOnce = (
  key: string,
  message: string,
  payload: Record<string, unknown>,
) => {
  const now = Date.now();
  const previous = streamWarnTimestamps.get(key);
  if (previous && now - previous < streamWarnThrottleMs) {
    return;
  }
  streamWarnTimestamps.set(key, now);
  console.warn(message, payload);
};
