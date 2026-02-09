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

const pickNumber = (obj: Record<string, unknown> | null, keys: string[]) => {
  if (!obj) return null;
  for (const key of keys) {
    const value = obj[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return null;
};

const toIsoStringMaybe = (value: number) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
};

const stringifyCompact = (value: unknown, limit = 800) => {
  try {
    const json = JSON.stringify(value);
    if (!json) return "";
    return json.length > limit ? `${json.slice(0, limit)}…` : json;
  } catch {
    return String(value ?? "");
  }
};

const extractTextFromParts = (parts: unknown[]) =>
  parts
    .map((part) => {
      if (!part || typeof part !== "object") return null;
      const typed = part as { kind?: unknown; type?: unknown; text?: unknown };
      const kind = typeof typed.kind === "string" ? typed.kind : "";
      const type = typeof typed.type === "string" ? typed.type : "";
      if (kind === "text" || type === "text") {
        return typeof typed.text === "string" ? typed.text : null;
      }
      return null;
    })
    .filter((item): item is string => Boolean(item))
    .join("");

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
  const direct = pickIsoDateString(obj, [
    "last_active_at",
    "updated_at",
    "created_at",
    "timestamp",
    "ts",
  ]);
  if (direct) return direct;

  // OpenCode sessions often expose timestamps as milliseconds under `time`.
  const time = asRecord(obj?.time);
  const ms =
    pickNumber(time, ["updated", "created"]) ??
    pickNumber(obj, ["updated", "created"]);
  if (typeof ms === "number") {
    return toIsoStringMaybe(ms);
  }
  return null;
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
  if (obj?.kind === "message") {
    const metadata = asRecord(obj.metadata);
    const opencode = asRecord(metadata?.opencode);
    const raw = asRecord(opencode?.raw);
    const info = asRecord(raw?.info);
    const role = pickString(info, ["role"]);
    if (role) return role;
  }
  return pickString(obj, ["role", "type", "sender"]) ?? "message";
};

export const getOpencodeMessageText = (item: unknown) => {
  const obj = asRecord(item);
  const direct = pickString(obj, ["text", "content", "message"]);
  if (direct) return direct;

  // A2A Message shape: { kind: "message", parts: [{ kind: "text", text: ... }] }
  if (obj?.kind === "message") {
    const parts = Array.isArray(obj.parts) ? obj.parts : [];
    const text = extractTextFromParts(parts);
    if (text) return text;

    // Fallback: OpenCode raw shape nested under metadata.
    const metadata = asRecord(obj.metadata);
    const opencode = asRecord(metadata?.opencode);
    const raw = asRecord(opencode?.raw);
    const rawParts = Array.isArray(raw?.parts) ? (raw?.parts as unknown[]) : [];
    const rawText = extractTextFromParts(rawParts);
    if (rawText) return rawText;
  }

  const content = obj?.content;
  if (typeof content === "string" && content.trim()) return content;

  return stringifyCompact(item);
};

export const getOpencodeMessageTimestamp = (item: unknown) => {
  const obj = asRecord(item);
  const direct = pickIsoDateString(obj, ["created_at", "timestamp", "ts"]);
  if (direct) return direct;

  if (obj?.kind === "message") {
    const metadata = asRecord(obj.metadata);
    const opencode = asRecord(metadata?.opencode);
    const raw = asRecord(opencode?.raw);
    const info = asRecord(raw?.info);
    const time = asRecord(info?.time);
    const created = time?.created;
    if (typeof created === "number") return toIsoStringMaybe(created);
    const completed = time?.completed;
    if (typeof completed === "number") return toIsoStringMaybe(completed);
  }

  const ms = pickNumber(obj, ["created", "updated"]);
  if (typeof ms === "number") {
    return toIsoStringMaybe(ms);
  }
  return null;
};
