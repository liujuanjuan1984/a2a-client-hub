import { AllowlistError, ApiConfigError } from "./api/client";

type ValidationErrorItem = {
  loc?: unknown;
  msg?: unknown;
  message?: unknown;
};

type ApiLikeError = {
  status: number;
  message: string;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object";

const parseJsonObject = (value: string): Record<string, unknown> | null => {
  if (!value.trim().startsWith("{")) return null;
  try {
    const parsed = JSON.parse(value);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
};

const extractValidationErrors = (
  payload: Record<string, unknown>,
): unknown[] => {
  if (Array.isArray(payload.errors)) return payload.errors;
  const detail = payload.detail;
  if (isRecord(detail) && Array.isArray(detail.errors)) {
    return detail.errors;
  }
  return [];
};

const getValidationField = (item: ValidationErrorItem): string | null => {
  const loc = item.loc;
  if (!Array.isArray(loc)) return null;
  for (let index = loc.length - 1; index >= 0; index -= 1) {
    const segment = loc[index];
    if (typeof segment === "string" && segment.trim()) {
      return segment.trim().toLowerCase();
    }
  }
  return null;
};

const toFriendlyValidationMessage = (item: unknown): string | null => {
  if (!isRecord(item)) return null;
  const field = getValidationField(item);
  if (field === "email") {
    return "Please enter a valid email address.";
  }
  if (field === "password") {
    return "Please enter a valid password.";
  }
  const message =
    typeof item.msg === "string"
      ? item.msg
      : typeof item.message === "string"
        ? item.message
        : null;
  if (message && message.trim()) {
    return message.trim();
  }
  return null;
};

const pickMessageFromPayload = (
  payload: Record<string, unknown>,
): string | null => {
  const directMessage =
    typeof payload.message === "string" ? payload.message.trim() : "";
  if (directMessage && directMessage !== "Validation error") {
    return directMessage;
  }
  const detail = payload.detail;
  if (isRecord(detail) && typeof detail.message === "string") {
    const nested = detail.message.trim();
    if (nested && nested !== "Validation error") {
      return nested;
    }
  }
  return null;
};

export const getFriendlyAuthErrorMessage = (error: unknown): string | null => {
  if (error instanceof AllowlistError) {
    return `Connection to \"${error.unauthorizedHost}\" is not allowed. Add it to the allowlist?`;
  }
  if (error instanceof ApiConfigError) {
    return error.message;
  }

  const errorRecord =
    error && typeof error === "object"
      ? (error as Record<string, unknown>)
      : null;
  const isApiLikeError =
    errorRecord !== null &&
    typeof errorRecord.status === "number" &&
    typeof errorRecord.message === "string";

  if (!isApiLikeError) {
    return error instanceof Error ? error.message : null;
  }
  const apiError = error as ApiLikeError;

  const raw = apiError.message.trim();
  const payload = parseJsonObject(raw);

  if (apiError.status === 422) {
    if (payload) {
      const first = extractValidationErrors(payload)[0];
      const friendly = toFriendlyValidationMessage(first);
      if (friendly) return friendly;
      const payloadMessage = pickMessageFromPayload(payload);
      if (payloadMessage) return payloadMessage;
    }
    return "Please check your input and try again.";
  }

  if (payload) {
    return pickMessageFromPayload(payload) ?? raw;
  }
  return raw || "Request failed.";
};
