import type { ChatMessage, StreamChunk } from "@/lib/api/chat-utils";

export const shouldSplitStreamMessage = (
  message: ChatMessage,
  chunk: StreamChunk,
) => {
  if (chunk.append) return false;
  if (!message.content) return false;
  const records = message.streamChunks ?? [];
  const last = records.length > 0 ? records[records.length - 1] : null;
  // If we're already receiving snapshot updates, keep updating the same message.
  if (last?.append === false) return false;
  return true;
};
