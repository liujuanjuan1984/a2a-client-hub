import { type Href } from "expo-router";

export const buildChatRoute = (agentId: string, conversationId: string) =>
  ({
    pathname: "/(app)/chat/[agentId]/[conversationId]",
    params: {
      agentId,
      conversationId,
    },
  }) as unknown as Href;

// Typed routes are generated into `.expo/types/router.d.ts` (gitignored).
// Keep casts centralized to avoid scattering `as Href` across the app code.
export const scheduledJobsHref = "/scheduled-jobs" as unknown as Href;
export const scheduledJobNewHref = "/scheduled-jobs/new" as unknown as Href;
export const buildScheduledJobEditHref = (jobId: string) =>
  `/scheduled-jobs/${jobId}` as unknown as Href;
