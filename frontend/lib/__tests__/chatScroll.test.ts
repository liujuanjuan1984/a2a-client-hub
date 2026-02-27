import {
  CHAT_LIST_BOTTOM_STICK_THRESHOLD,
  getAnchoredOffsetAfterContentResize,
  getDistanceToBottom,
  shouldShowScrollToBottom,
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

  describe("shouldShowScrollToBottom", () => {
    it("returns false when content is shorter than viewport", () => {
      expect(
        shouldShowScrollToBottom({
          offsetY: 0,
          viewportHeight: 600,
          contentHeight: 400,
        }),
      ).toBe(false);
    });

    it("returns true when distance to bottom exceeds one screen height", () => {
      expect(
        shouldShowScrollToBottom({
          offsetY: 100,
          viewportHeight: 600,
          contentHeight: 2000,
        }),
      ).toBe(true);
    });

    it("returns false when distance to bottom is within one screen height", () => {
      expect(
        shouldShowScrollToBottom({
          offsetY: 1000,
          viewportHeight: 600,
          contentHeight: 2000,
        }),
      ).toBe(false);
    });

    it("supports custom threshold", () => {
      expect(
        shouldShowScrollToBottom(
          {
            offsetY: 1000,
            viewportHeight: 600,
            contentHeight: 2000,
          },
          200,
        ),
      ).toBe(true);
    });
  });

  it("computes anchored offset when content grows", () => {
    expect(
      getAnchoredOffsetAfterContentResize(
        { offset: 200, contentHeight: 1000 },
        1120,
      ),
    ).toBe(320);
  });

  it("computes anchored offset when content shrinks", () => {
    expect(
      getAnchoredOffsetAfterContentResize(
        { offset: 200, contentHeight: 1000 },
        920,
      ),
    ).toBe(120);
  });

  it("clamps anchored offset to zero when shrink exceeds offset", () => {
    expect(
      getAnchoredOffsetAfterContentResize(
        { offset: 60, contentHeight: 1000 },
        900,
      ),
    ).toBe(0);
  });
});
