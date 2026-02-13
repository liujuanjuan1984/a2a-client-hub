export type UnifiedSessionSource = "manual" | "scheduled" | "opencode";

const MANUAL_PREFIX = "manual:";
const SCHEDULED_PREFIX = "scheduled:";
const OPENCODE_PREFIX = "opencode:";

const toBase64 = (value: string) => {
  if (typeof globalThis.btoa === "function") {
    return globalThis.btoa(value);
  }
  const maybeBuffer = (globalThis as { Buffer?: typeof Buffer }).Buffer;
  if (maybeBuffer) {
    return maybeBuffer.from(value, "utf-8").toString("base64");
  }
  throw new Error("No base64 encoder is available in this runtime.");
};

const base64UrlEncode = (value: string) => {
  const encoded = toBase64(value);
  return encoded.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
};

export const buildScheduledSessionId = (sessionId: string) =>
  `${SCHEDULED_PREFIX}${sessionId}`;

export const buildOpencodeSessionId = (options: {
  agentId: string;
  agentSource: "personal" | "shared";
  upstreamSessionId: string;
}) => {
  const payload = JSON.stringify({
    agent_id: options.agentId,
    agent_source: options.agentSource,
    session_id: options.upstreamSessionId,
  });
  return `${OPENCODE_PREFIX}${base64UrlEncode(payload)}`;
};

export const getSessionSource = (
  sessionId: string,
): UnifiedSessionSource | null => {
  if (sessionId.startsWith(MANUAL_PREFIX)) return "manual";
  if (sessionId.startsWith(SCHEDULED_PREFIX)) return "scheduled";
  if (sessionId.startsWith(OPENCODE_PREFIX)) return "opencode";
  return null;
};
