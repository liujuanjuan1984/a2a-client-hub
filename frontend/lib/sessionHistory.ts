import { type ChatMessage, type ChatRole } from "@/lib/api/chat-utils";

export type SessionMessageItem = {
  id?: string;
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
  sessionId: string,
): ChatMessage[] =>
  items
    .map((item, index) => ({
      id:
        typeof item.id === "string" && item.id
          ? item.id
          : `${sessionId}-${item.created_at}-${index}`,
      role: normalizeSessionMessageRole(item.role),
      content: item.content ?? "",
      createdAt: item.created_at,
      status: "done" as const,
    }))
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
