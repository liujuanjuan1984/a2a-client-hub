import {
  type ChatMessage,
  type ChatRole,
  type MessageBlock,
} from "@/lib/api/chat-utils";

export type SessionMessageItem = {
  id?: string;
  role: string;
  content: string;
  created_at: string;
  metadata?: Record<string, unknown> | null;
};

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const parseMetadataBlocks = (
  metadata: Record<string, unknown> | null | undefined,
): MessageBlock[] => {
  const metadataRecord = asRecord(metadata);
  const opencodeRecord =
    asRecord(metadataRecord?.opencode_stream) ??
    asRecord(metadataRecord?.opencodeStream);
  const candidates =
    metadataRecord?.message_blocks ??
    metadataRecord?.messageBlocks ??
    opencodeRecord?.blocks;
  if (!Array.isArray(candidates)) return [];

  return candidates
    .map((item, index) => {
      const record = asRecord(item);
      if (!record) return null;
      const type = typeof record.type === "string" ? record.type.trim() : "";
      const content = typeof record.content === "string" ? record.content : "";
      if (!type || !content) return null;
      const isFinished =
        record.isFinished === true ||
        record.is_finished === true ||
        record.done === true;
      const createdAt =
        typeof record.createdAt === "string" && record.createdAt.trim()
          ? record.createdAt
          : typeof record.created_at === "string" && record.created_at.trim()
            ? record.created_at
            : new Date(0).toISOString();
      const updatedAt =
        typeof record.updatedAt === "string" && record.updatedAt.trim()
          ? record.updatedAt
          : typeof record.updated_at === "string" && record.updated_at.trim()
            ? record.updated_at
            : createdAt;
      return {
        id:
          typeof record.id === "string" && record.id.trim()
            ? record.id
            : `history-block-${index}`,
        type,
        content,
        isFinished,
        createdAt,
        updatedAt,
      };
    })
    .filter((item): item is MessageBlock => Boolean(item));
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
  sessionId: string,
): ChatMessage[] =>
  items
    .map((item, index) => {
      const role = normalizeSessionMessageRole(item.role);
      const messageId =
        typeof item.id === "string" && item.id
          ? item.id
          : `${sessionId}-${item.created_at}-${index}`;
      const metadataBlocks = parseMetadataBlocks(item.metadata);
      const blocks =
        role === "agent" && metadataBlocks.length === 0 && item.content
          ? [
              {
                id: `${messageId}:text`,
                type: "text",
                content: item.content,
                isFinished: true,
                createdAt: item.created_at,
                updatedAt: item.created_at,
              },
            ]
          : metadataBlocks;
      return {
        id: messageId,
        role,
        content: item.content ?? "",
        createdAt: item.created_at,
        status: "done" as const,
        blocks: role === "agent" ? blocks : [],
      };
    })
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
