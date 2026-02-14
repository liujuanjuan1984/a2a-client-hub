export type UnifiedSessionSource =
  | "manual"
  | "scheduled"
  | "opencode"
  | "conversation";

const MANUAL_PREFIX = "manual:";
const SCHEDULED_PREFIX = "scheduled:";
const OPENCODE_PREFIX = "opencode:";
const CONVERSATION_PREFIX = "conversation:";

export const buildScheduledSessionId = (sessionId: string) =>
  `${SCHEDULED_PREFIX}${sessionId}`;

export const buildConversationSessionId = (sessionId: string) =>
  `${CONVERSATION_PREFIX}${sessionId}`;

export const getSessionSource = (
  sessionId: string,
): UnifiedSessionSource | null => {
  if (sessionId.startsWith(MANUAL_PREFIX)) return "manual";
  if (sessionId.startsWith(SCHEDULED_PREFIX)) return "scheduled";
  if (sessionId.startsWith(OPENCODE_PREFIX)) return "opencode";
  if (sessionId.startsWith(CONVERSATION_PREFIX)) return "conversation";
  return null;
};
