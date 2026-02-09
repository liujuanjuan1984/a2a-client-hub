import { type ChatMessage } from "@/lib/api/chat-utils";
import {
  getOpencodeMessageId,
  getOpencodeMessageRole,
  getOpencodeMessageText,
  getOpencodeMessageTimestamp,
} from "@/lib/opencodeAdapters";

const toChatRole = (raw: string): ChatMessage["role"] => {
  const normalized = (raw || "").trim().toLowerCase();
  if (!normalized) return "system";
  if (normalized === "user" || normalized === "human") return "user";
  if (normalized === "assistant" || normalized === "agent") return "agent";
  if (normalized === "system") return "system";
  return "system";
};

export const mapOpencodeMessagesToChatMessages = (
  items: unknown[],
): ChatMessage[] => {
  const now = new Date().toISOString();
  return items.map((item) => {
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
