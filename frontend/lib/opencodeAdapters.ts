const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;

const pickString = (obj: Record<string, unknown> | null, keys: string[]) => {
  if (!obj) return null;
  for (const key of keys) {
    const value = obj[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return null;
};

const pickIsoDateString = (
  obj: Record<string, unknown> | null,
  keys: string[],
) => pickString(obj, keys);

const stringifyCompact = (value: unknown, limit = 800) => {
  try {
    const json = JSON.stringify(value);
    if (!json) return "";
    return json.length > limit ? `${json.slice(0, limit)}…` : json;
  } catch {
    return String(value ?? "");
  }
};

export const getOpencodeSessionId = (item: unknown) => {
  const obj = asRecord(item);
  return (
    pickString(obj, ["id", "session_id", "sessionId"]) ??
    stringifyCompact(item, 120)
  );
};

export const getOpencodeSessionTitle = (item: unknown) => {
  const obj = asRecord(item);
  return (
    pickString(obj, ["title", "name", "label"]) ??
    pickString(obj, ["id", "session_id", "sessionId"]) ??
    "Session"
  );
};

export const getOpencodeSessionTimestamp = (item: unknown) => {
  const obj = asRecord(item);
  return pickIsoDateString(obj, [
    "last_active_at",
    "updated_at",
    "created_at",
    "timestamp",
    "ts",
  ]);
};

export const getOpencodeMessageId = (item: unknown) => {
  const obj = asRecord(item);
  return (
    pickString(obj, ["id", "message_id", "messageId"]) ??
    stringifyCompact(item, 120)
  );
};

export const getOpencodeMessageRole = (item: unknown) => {
  const obj = asRecord(item);
  return pickString(obj, ["role", "type", "sender"]) ?? "message";
};

export const getOpencodeMessageText = (item: unknown) => {
  const obj = asRecord(item);
  const direct = pickString(obj, ["text", "content", "message"]);
  if (direct) return direct;

  const content = obj?.content;
  if (typeof content === "string" && content.trim()) return content;

  return stringifyCompact(item);
};

export const getOpencodeMessageTimestamp = (item: unknown) => {
  const obj = asRecord(item);
  return pickIsoDateString(obj, ["created_at", "timestamp", "ts"]);
};
