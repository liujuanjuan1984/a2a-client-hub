import { type Href } from "expo-router";

export const buildChatRoute = (
  agentId: string,
  sessionId: string,
  options?: {
    history?: boolean;
    source?: "manual" | "scheduled";
    opencodeSessionId?: string;
  },
) =>
  ({
    pathname: "/(app)/chat/[agentId]/[sessionId]",
    params: {
      agentId,
      sessionId,
      ...(options?.history ? { history: "1" } : {}),
      ...(options?.source ? { source: options.source } : {}),
      ...(options?.opencodeSessionId
        ? { opencodeSessionId: options.opencodeSessionId }
        : {}),
    },
  }) as unknown as Href;

export const buildOpencodeSessionsRoute = (agentId: string) =>
  ({
    pathname: "/(app)/opencode/[agentId]/sessions",
    params: { agentId },
  }) as unknown as Href;

export const buildOpencodeSessionMessagesRoute = (
  agentId: string,
  sessionId: string,
) =>
  ({
    pathname: "/(app)/opencode/[agentId]/sessions/[sessionId]",
    params: { agentId, sessionId },
  }) as unknown as Href;

// Typed routes are generated into `.expo/types/router.d.ts` (gitignored).
// Keep casts centralized to avoid scattering `as Href` across the app code.
export const scheduledJobsHref = "/scheduled-jobs" as unknown as Href;
export const scheduledJobNewHref = "/scheduled-jobs/new" as unknown as Href;
export const buildScheduledJobEditHref = (jobId: string) =>
  `/scheduled-jobs/${jobId}` as unknown as Href;
