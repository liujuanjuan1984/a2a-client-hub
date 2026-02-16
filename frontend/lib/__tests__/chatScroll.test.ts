import {
  CHAT_LIST_BOTTOM_STICK_THRESHOLD,
  getDistanceToBottom,
  shouldStickToBottom,
} from "@/lib/chatScroll";

describe("chatScroll", () => {
  it("computes distance to bottom from scroll metrics", () => {
    expect(
      getDistanceToBottom({
        offsetY: 120,
        viewportHeight: 600,
        contentHeight: 1000,
      }),
    ).toBe(280);
  });

  it("sticks to bottom when distance is within threshold", () => {
    expect(
      shouldStickToBottom({
        offsetY: 328,
        viewportHeight: 600,
        contentHeight: 1000,
      }),
    ).toBe(true);
    expect(
      shouldStickToBottom({
        offsetY: 327,
        viewportHeight: 600,
        contentHeight: 1000,
      }),
    ).toBe(false);
  });

  it("treats short content as bottom-aligned", () => {
    expect(
      shouldStickToBottom({
        offsetY: 0,
        viewportHeight: 700,
        contentHeight: 640,
      }),
    ).toBe(true);
  });

  it("supports custom threshold", () => {
    expect(
      shouldStickToBottom(
        {
          offsetY: 300,
          viewportHeight: 600,
          contentHeight: 1000,
        },
        CHAT_LIST_BOTTOM_STICK_THRESHOLD + 30,
      ),
    ).toBe(true);
  });
});
