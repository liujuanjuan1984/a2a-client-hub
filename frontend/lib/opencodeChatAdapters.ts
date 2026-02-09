import { type ChatMessage } from "@/lib/api/chat-utils";
import {
  getOpencodeMessageId,
  getOpencodeMessageRole,
  getOpencodeMessageText,
  getOpencodeMessageTimestamp,
} from "@/lib/opencodeAdapters";

type A2ATextPart = {
  kind?: unknown;
  type?: unknown;
  text?: unknown;
};

type A2AMessageLike = {
  kind?: unknown;
  messageId?: unknown;
  role?: unknown;
  parts?: unknown;
  createdAt?: unknown;
  created_at?: unknown;
  timestamp?: unknown;
  metadata?: unknown;
};

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;

const coerceString = (value: unknown) =>
  typeof value === "string" && value.trim() ? value.trim() : null;

const isA2AMessage = (value: unknown): value is A2AMessageLike => {
  const obj = asRecord(value);
  if (!obj) return false;
  if (obj.kind !== "message") return false;
  if (typeof obj.messageId !== "string" || !obj.messageId.trim()) return false;
  return true;
};

const extractA2AText = (value: unknown): string => {
  const obj = asRecord(value);
  const parts = Array.isArray(obj?.parts) ? (obj?.parts as unknown[]) : [];
  const texts = parts
    .map((part) => {
      if (!part || typeof part !== "object") return null;
      const typed = part as A2ATextPart;
      const kind = typeof typed.kind === "string" ? typed.kind : "";
      const type = typeof typed.type === "string" ? typed.type : "";
      if (kind === "text" || type === "text") {
        return typeof typed.text === "string" ? typed.text : null;
      }
      return null;
    })
    .filter((text): text is string => Boolean(text));
  return texts.join("");
};

const extractOpencodeRoleFromMetadata = (value: unknown): string | null => {
  const obj = asRecord(value);
  const metadata = asRecord(obj?.metadata);
  const opencode = asRecord(metadata?.opencode);
  const raw = asRecord(opencode?.raw);
  const info = asRecord(raw?.info);
  return coerceString(info?.role);
};

const toChatRole = (raw: string): ChatMessage["role"] => {
  const normalized = (raw || "").trim().toLowerCase();
  if (!normalized) return "system";
  if (normalized === "user" || normalized === "human") return "user";
  if (normalized === "assistant" || normalized === "agent") return "agent";
  if (normalized === "system") return "system";
  return "system";
};

const toIsoFromMsMaybe = (value: unknown): string | null => {
  const ms = typeof value === "number" && Number.isFinite(value) ? value : null;
  if (ms === null) return null;
  const date = new Date(ms);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
};

const extractA2ATimestamp = (value: unknown): string | null => {
  const obj = asRecord(value);
  const direct =
    coerceString(obj?.createdAt) ??
    coerceString(obj?.created_at) ??
    coerceString(obj?.timestamp);
  if (direct) return direct;

  // Fallback: OpenCode raw carries ms timestamps in metadata.
  const metadata = asRecord(obj?.metadata);
  const opencode = asRecord(metadata?.opencode);
  const raw = asRecord(opencode?.raw);
  const info = asRecord(raw?.info);
  const time = asRecord(info?.time);
  return toIsoFromMsMaybe(time?.created) ?? toIsoFromMsMaybe(time?.completed);
};

export const mapOpencodeMessagesToChatMessages = (
  items: unknown[],
): ChatMessage[] => {
  const now = new Date().toISOString();
  return items.map((item) => {
    if (isA2AMessage(item)) {
      const id = coerceString(item.messageId) ?? "message";
      const roleRaw =
        coerceString(item.role) ?? extractOpencodeRoleFromMetadata(item) ?? "";
      const role = toChatRole(roleRaw);
      const createdAt = extractA2ATimestamp(item) ?? now;
      const content = extractA2AText(item);
      return {
        id: `opencode:${id}`,
        role,
        content: content || "(empty message)",
        createdAt,
        status: "done",
      };
    }

    const id = getOpencodeMessageId(item) || "message";
    const role = toChatRole(getOpencodeMessageRole(item));
    const createdAt = getOpencodeMessageTimestamp(item) ?? now;
    return {
      id: `opencode:${id}`,
      role,
      content: getOpencodeMessageText(item),
      createdAt,
      status: "done",
    };
  });
};
