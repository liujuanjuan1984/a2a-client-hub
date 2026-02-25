import { type ChatMessage, type ChatRole } from "@/lib/api/chat-utils";

const normalizeAgentContent = (content: string): string => {
  const normalized = content.trim();
  if (
    normalized.length < 2 ||
    normalized[0] !== '"' ||
    normalized.slice(-1) !== '"'
  ) {
    return normalized;
  }

  try {
    const parsed = JSON.parse(normalized);
    return typeof parsed === "string" ? parsed : normalized;
  } catch {
    return normalized.slice(1, -1);
  }
};

export type SessionMessageItem = {
  id: string;
  role: string;
  content: string;
  created_at: string;
  metadata?: Record<string, unknown> | null;
};

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const pickTrimmedString = (
  source: Record<string, unknown> | null,
  keys: string[],
): string | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
};

const parseClientMessageId = (
  metadata: Record<string, unknown> | null | undefined,
): string | null => {
  const metadataRecord = asRecord(metadata);
  return pickTrimmedString(metadataRecord, [
    "client_message_id",
    "clientMessageId",
    "request_message_id",
    "requestMessageId",
  ]);
};

const parseUpstreamMessageId = (
  metadata: Record<string, unknown> | null | undefined,
): string | null => {
  const metadataRecord = asRecord(metadata);
  return pickTrimmedString(metadataRecord, [
    "upstream_message_id",
    "message_id",
    "messageId",
  ]);
};

const normalizeSessionMessageRole = (value: string): ChatRole => {
  const role = value.toLowerCase();
  if (role === "assistant") return "agent";
  if (role === "agent") return "agent";
  if (role === "user") return "user";
  return "system";
};

export const mapSessionMessagesToChatMessages = (
  items: SessionMessageItem[],
): ChatMessage[] => {
  const mapped: ChatMessage[] = [];
  items.forEach((item) => {
    const role = normalizeSessionMessageRole(item.role);
    const normalizedContent =
      role === "agent" ? normalizeAgentContent(item.content) : item.content;
    const messageId = typeof item.id === "string" ? item.id.trim() : "";
    if (!messageId) {
      return;
    }
    const blocks =
      role === "agent" && normalizedContent
        ? [
            {
              id: `${messageId}:text`,
              type: "text",
              content: normalizedContent,
              isFinished: true,
              createdAt: item.created_at,
              updatedAt: item.created_at,
            },
          ]
        : [];
    mapped.push({
      id: messageId,
      role,
      content: normalizedContent ?? "",
      createdAt: item.created_at,
      status: "done" as const,
      blocks: role === "agent" ? blocks : [],
      clientMessageId: parseClientMessageId(item.metadata) ?? undefined,
      upstreamMessageId: parseUpstreamMessageId(item.metadata) ?? undefined,
    });
  });
  return mapped.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
};
