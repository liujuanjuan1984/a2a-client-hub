import { type StreamChunk } from "@/lib/api/chat-utils";
import {
  applyStreamChunk,
  MAX_STREAM_CHUNK_CHARS,
  MAX_STREAM_CHUNK_COUNT,
  trimStreamChunks,
} from "@/lib/streamChunks";

describe("streamChunks helpers", () => {
  it("applies append=false snapshots without losing chunk history", () => {
    const appendChunk: StreamChunk = { text: "Hello ", append: true };
    const appendChunk2: StreamChunk = { text: "World", append: true };
    const snapshotChunk: StreamChunk = { text: "Reset ", append: false };
    const appendAfterSnapshot: StreamChunk = { text: "Again", append: true };

    const first = applyStreamChunk("", [], appendChunk);
    const second = applyStreamChunk(
      first.content,
      first.streamChunks,
      appendChunk2,
    );
    const third = applyStreamChunk(
      second.content,
      second.streamChunks,
      snapshotChunk,
    );
    const fourth = applyStreamChunk(
      third.content,
      third.streamChunks,
      appendAfterSnapshot,
    );

    expect(fourth.content).toBe("Reset Again");
    expect(fourth.streamChunks).toEqual([
      { text: "Hello ", append: true },
      { text: "World", append: true },
      { text: "Reset ", append: false },
      { text: "Again", append: true },
    ]);
  });

  it("trims stream chunk buffer by count and total chars", () => {
    const oversized = { text: "x".repeat(100), append: true };
    const chunks = Array.from({ length: 400 }, () => oversized);

    const trimmed = trimStreamChunks(chunks);

    expect(trimmed.length).toBeLessThanOrEqual(MAX_STREAM_CHUNK_COUNT);
    expect(
      trimmed.reduce((sum, item) => sum + item.text.length, 0),
    ).toBeLessThanOrEqual(MAX_STREAM_CHUNK_CHARS);
  });
});
