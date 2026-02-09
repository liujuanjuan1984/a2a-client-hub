import type { ChatMessage, StreamChunk } from "@/lib/api/chat-utils";
import { shouldSplitStreamMessage } from "@/lib/streamMessageSplit";

const baseMessage = (overrides?: Partial<ChatMessage>): ChatMessage => ({
  id: "m1",
  role: "agent",
  content: "",
  createdAt: new Date(0).toISOString(),
  status: "streaming",
  streamChunks: [],
  ...(overrides ?? {}),
});

describe("shouldSplitStreamMessage", () => {
  it("does not split for append=true chunks", () => {
    const message = baseMessage({ content: "Hello" });
    const chunk: StreamChunk = { text: " world", append: true };
    expect(shouldSplitStreamMessage(message, chunk)).toBe(false);
  });

  it("does not split when message is empty", () => {
    const message = baseMessage({ content: "" });
    const chunk: StreamChunk = { text: "Snapshot", append: false };
    expect(shouldSplitStreamMessage(message, chunk)).toBe(false);
  });

  it("splits when switching from append=true stream to append=false snapshot", () => {
    const message = baseMessage({
      content: "partial",
      streamChunks: [{ text: "partial", append: true }],
    });
    const chunk: StreamChunk = { text: "snapshot", append: false };
    expect(shouldSplitStreamMessage(message, chunk)).toBe(true);
  });

  it("does not split for consecutive append=false snapshots", () => {
    const message = baseMessage({
      content: "snapshot1",
      streamChunks: [{ text: "snapshot1", append: false }],
    });
    const chunk: StreamChunk = { text: "snapshot2", append: false };
    expect(shouldSplitStreamMessage(message, chunk)).toBe(false);
  });
});
