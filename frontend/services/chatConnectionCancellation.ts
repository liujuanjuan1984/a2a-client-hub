import { ApiRequestError } from "@/lib/api/client";

export const isSessionNotFoundCancellationError = (error: unknown): boolean => {
  if (!(error instanceof ApiRequestError)) {
    return false;
  }
  if (error.errorCode === "session_not_found") {
    return true;
  }
  if (error.status !== 404) {
    return false;
  }
  return error.message.includes("session_not_found");
};
