import {
  type ChatMessage,
  type ChatRole,
  type MessageBlock,
  projectPrimaryTextContent,
} from "@/lib/api/chat-utils";

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
  created_at: string;
  metadata?: Record<string, unknown> | null;
  content?: string;
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
    const mappedBlocks = role === "agent" ? mapBlocks(item) : [];
    const fallbackContent =
      typeof item.content === "string"
        ? role === "agent"
          ? normalizeAgentContent(item.content)
          : item.content
        : "";
    const blocks =
      role === "agent" && mappedBlocks.length === 0 && fallbackContent
        ? [
            {
              id: `${messageId}:1`,
              type: "text",
              content: fallbackContent,
              isFinished: true,
              createdAt: item.created_at,
              updatedAt: item.created_at,
            },
          ]
        : mappedBlocks;
    const normalizedContent =
      role === "agent"
        ? blocks.length > 0
          ? projectPrimaryTextContent(blocks)
          : fallbackContent
        : fallbackContent;
    mapped.push({
      id: messageId,
      role,
      content: normalizedContent ?? "",
      createdAt: item.created_at,
      status: "done" as const,
      blocks: role === "agent" ? blocks : [],
    });
  });
  return mapped.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
};
