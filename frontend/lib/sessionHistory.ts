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
    });
  });
  return mapped.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
};
