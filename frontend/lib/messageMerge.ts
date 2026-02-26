import { type ChatMessage } from "@/lib/api/chat-utils";

const normalizeMessageKey = (
  value: string | null | undefined,
): string | null => {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

export const mergeChatMessagesByCanonicalId = (options: {
  current: ChatMessage[];
  incoming: ChatMessage[];
  isActivelyStreaming: boolean;
}): ChatMessage[] => {
  const { current, incoming, isActivelyStreaming } = options;
  const merged = new Map<string, ChatMessage>();
  current.forEach((message) => {
    merged.set(message.id, message);
  });

  incoming.forEach((message) => {
    const canonicalId = normalizeMessageKey(message.id);
    if (!canonicalId) return;
    const existing = merged.get(canonicalId);

    if (existing && existing.status === "streaming" && isActivelyStreaming) {
      return;
    }

    const next = existing
      ? { ...existing, ...message, id: canonicalId }
      : { ...message, id: canonicalId };
    merged.set(canonicalId, next);
  });

  return Array.from(merged.values()).sort((left, right) =>
    left.createdAt.localeCompare(right.createdAt),
  );
};
