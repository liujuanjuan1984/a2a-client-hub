import {
  buildProcessStates,
  sanitizeStreamRecords,
} from "@/lib/streamChunkView";

describe("streamChunkView helpers", () => {
  it("keeps only one terminal duplicate snapshot", () => {
    const records = sanitizeStreamRecords(
      [
        { text: "Hello", append: false },
        { text: "Hello", append: false },
        { text: "Hello", append: false },
      ],
      "Hello",
    );
    expect(records).toEqual([{ text: "Hello", append: false }]);
  });

  it("builds process states from append=false snapshots", () => {
    expect(
      buildProcessStates(
        sanitizeStreamRecords([
          { text: "你", append: false },
          { text: "你好", append: false },
          { text: "你好世", append: false },
          { text: "你好世界", append: false },
        ]),
      ),
    ).toEqual(["你", "你好", "你好世", "你好世界"]);
  });

  it("builds process states from append=true chunks", () => {
    expect(
      buildProcessStates(
        sanitizeStreamRecords([
          { text: "Hello ", append: true },
          { text: "world", append: true },
          { text: "!", append: true },
        ]),
      ),
    ).toEqual(["Hello ", "Hello world", "Hello world!"]);
  });

  it("keeps rewrite snapshots as distinct process states", () => {
    expect(
      buildProcessStates(
        sanitizeStreamRecords([
          { text: "hello world", append: false },
          { text: "summary", append: false },
        ]),
      ),
    ).toEqual(["hello world", "summary"]);
  });
});
