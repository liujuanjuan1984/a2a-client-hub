export type UnifiedSessionSource = "manual" | "scheduled" | "opencode";

const MANUAL_PREFIX = "manual:";
const SCHEDULED_PREFIX = "scheduled:";
const OPENCODE_PREFIX = "opencode:";

export const buildScheduledSessionId = (sessionId: string) =>
  `${SCHEDULED_PREFIX}${sessionId}`;

export const getSessionSource = (
  sessionId: string,
): UnifiedSessionSource | null => {
  if (sessionId.startsWith(MANUAL_PREFIX)) return "manual";
  if (sessionId.startsWith(SCHEDULED_PREFIX)) return "scheduled";
  if (sessionId.startsWith(OPENCODE_PREFIX)) return "opencode";
  return null;
};
