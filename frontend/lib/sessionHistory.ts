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
  status?: string;
  blocks?: {
    id: string;
    type: string;
    content?: string | null;
    isFinished: boolean;
  }[];
};

type MapSessionMessagesOptions = {
  keepEmptyMessages?: boolean;
};

const normalizeSessionMessageRole = (value: string): ChatRole => {
  const role = value.toLowerCase();
  if (role === "assistant") return "agent";
  if (role === "agent") return "agent";
  if (role === "user") return "user";
  return "system";
};

const resolveMessageStatus = (
  status: unknown,
): NonNullable<ChatMessage["status"]> => {
  if (typeof status !== "string") {
    return "done";
  }
  const normalized = status.trim().toLowerCase();
  if (normalized === "streaming" || normalized === "in_progress") {
    return "streaming";
  }
  if (normalized === "error" || normalized === "failed") {
    return "error";
  }
  if (
    normalized === "interrupted" ||
    normalized === "cancelled" ||
    normalized === "canceled"
  ) {
    return "interrupted";
  }
  return "done";
};

const rolePriority = (role: ChatRole): number => {
  if (role === "user") return 0;
  if (role === "agent") return 1;
  return 2;
};

const mapBlocks = (item: SessionMessageItem): MessageBlock[] => {
  if (!Array.isArray(item.blocks) || item.blocks.length === 0) {
    return [];
  }
  const createdAt = item.created_at;
  return item.blocks.map((block, index) => {
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
  options?: MapSessionMessagesOptions,
): ChatMessage[] => {
  const keepEmptyMessages = options?.keepEmptyMessages === true;
  const mapped: ChatMessage[] = [];
  items.forEach((item) => {
    const role = normalizeSessionMessageRole(item.role);
    const messageId = typeof item.id === "string" ? item.id.trim() : "";
    if (!messageId) {
      return;
    }
    const blocks = mapBlocks(item);
    const blockContent = projectPrimaryTextContent(blocks);
    const normalizedContent =
      blockContent.trim().length > 0 ? blockContent : "";
    if (normalizedContent.trim().length === 0 && !keepEmptyMessages) {
      return;
    }
    mapped.push({
      id: messageId,
      role,
      content: normalizedContent,
      createdAt: item.created_at,
      status: resolveMessageStatus(item.status),
      blocks,
    });
  });
  return mapped.sort((left, right) => {
    const timeDiff = left.createdAt.localeCompare(right.createdAt);
    if (timeDiff !== 0) {
      return timeDiff;
    }
    const roleDiff = rolePriority(left.role) - rolePriority(right.role);
    if (roleDiff !== 0) {
      return roleDiff;
    }
    return left.id.localeCompare(right.id);
  });
};
