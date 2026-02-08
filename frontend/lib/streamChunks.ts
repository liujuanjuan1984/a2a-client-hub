import type { StreamChunk, StreamChunkRecord } from "@/lib/api/chat-utils";

export const MAX_STREAM_CHUNK_COUNT = 300;
export const MAX_STREAM_CHUNK_CHARS = 12_000;

const normalizeRecord = (
  chunk: StreamChunkRecord | string,
): StreamChunkRecord =>
  typeof chunk === "string" ? { text: chunk, append: true } : chunk;

export const trimStreamChunks = (chunks: StreamChunkRecord[]) => {
  if (chunks.length === 0) return chunks;

  let next = chunks;
  if (next.length > MAX_STREAM_CHUNK_COUNT) {
    next = next.slice(-MAX_STREAM_CHUNK_COUNT);
  }

  let totalChars = next.reduce((sum, item) => sum + item.text.length, 0);
  while (totalChars > MAX_STREAM_CHUNK_CHARS && next.length > 1) {
    totalChars -= next[0].text.length;
    next = next.slice(1);
  }

  return next;
};

export const applyStreamChunk = (
  content: string,
  streamChunks: (StreamChunkRecord | string)[] | undefined,
  chunk: StreamChunk,
) => {
  const normalized = (streamChunks ?? []).map(normalizeRecord);
  const nextContent = chunk.append ? `${content}${chunk.text}` : chunk.text;
  const nextChunks = trimStreamChunks([
    ...normalized,
    { text: chunk.text, append: chunk.append },
  ]);

  return {
    content: nextContent,
    streamChunks: nextChunks,
  };
};
