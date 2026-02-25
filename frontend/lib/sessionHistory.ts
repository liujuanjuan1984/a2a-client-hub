import {
  type ChatMessage,
  type ChatRole,
  type MessageBlock,
  projectPrimaryTextContent,
} from "@/lib/api/chat-utils";

export type SessionMessageItem = {
  id: string;
  role: string;
  created_at: string;
  metadata?: Record<string, unknown> | null;
  blocks?: {
    id: string;
    messageId: string;
    seq: number;
    type: string;
    content?: string | null;
    isFinished: boolean;
  }[];
};

const normalizeSessionMessageRole = (value: string): ChatRole => {
  const role = value.toLowerCase();
  if (role === "assistant") return "agent";
  if (role === "agent") return "agent";
  if (role === "user") return "user";
  return "system";
};

const mapBlocks = (item: SessionMessageItem): MessageBlock[] => {
  if (!Array.isArray(item.blocks) || item.blocks.length === 0) {
    return [];
  }
  const createdAt = item.created_at;
  return [...item.blocks]
    .sort((lhs, rhs) => lhs.seq - rhs.seq)
    .map((block, index) => {
      const blockId =
        typeof block.id === "string" && block.id.trim()
          ? block.id
          : `${item.id}:${index + 1}`;
      return {
        id: blockId,
        type: block.type,
        content: typeof block.content === "string" ? block.content : "",
        isFinished: block.isFinished === true,
        createdAt,
        updatedAt: createdAt,
      };
    });
};

export const mapSessionMessagesToChatMessages = (
  items: SessionMessageItem[],
): ChatMessage[] => {
  const mapped: ChatMessage[] = [];
  items.forEach((item) => {
    const role = normalizeSessionMessageRole(item.role);
    const messageId = typeof item.id === "string" ? item.id.trim() : "";
    if (!messageId) {
      return;
    }
    const blocks = mapBlocks(item);
    const normalizedContent = projectPrimaryTextContent(blocks);
    const hasRenderablePayload = normalizedContent.trim().length > 0;
    if (!hasRenderablePayload) {
      return;
    }
    mapped.push({
      id: messageId,
      role,
      content: normalizedContent ?? "",
      createdAt: item.created_at,
      status: "done" as const,
      blocks,
    });
  });
  return mapped.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
};
