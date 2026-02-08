import type { StreamChunkRecord } from "@/lib/api/chat-utils";

type StreamChunkInput = StreamChunkRecord | string;

const normalizeRecord = (chunk: StreamChunkInput): StreamChunkRecord =>
  typeof chunk === "string" ? { text: chunk, append: true } : chunk;

export const sanitizeStreamRecords = (
  streamChunks: StreamChunkInput[] | undefined,
  finalContent?: string,
) => {
  const normalized = (streamChunks ?? []).map(normalizeRecord);
  const records: StreamChunkRecord[] = [];

  normalized.forEach((chunk) => {
    const last = records[records.length - 1];
    const isTerminalDuplicate =
      !chunk.append &&
      Boolean(finalContent) &&
      chunk.text === finalContent &&
      last &&
      !last.append &&
      last.text === chunk.text;
    if (!isTerminalDuplicate) {
      records.push(chunk);
    }
  });

  return records;
};

export const buildProcessStates = (records: StreamChunkRecord[]) => {
  let state = "";
  const states: string[] = [];

  records.forEach((record) => {
    state = record.append ? `${state}${record.text}` : record.text;
    if (states[states.length - 1] !== state) {
      states.push(state);
    }
  });

  return states;
};
