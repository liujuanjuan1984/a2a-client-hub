import { fireEvent, render, waitFor } from "@testing-library/react-native";
import React from "react";

import { ReasoningBlock } from "../blocks/ReasoningBlock";

const mockMarkdownRender = jest.fn(
  ({ content }: { content: string; isAgent?: boolean }) => content,
);

jest.mock("../MarkdownRender", () => ({
  MarkdownRender: (props: { content: string; isAgent?: boolean }) => {
    mockMarkdownRender(props);
    return null;
  },
}));

describe("ReasoningBlock", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders markdown only after expanding", async () => {
    const onLayoutChangeStart = jest.fn();
    const screen = render(
      <ReasoningBlock
        block={{
          id: "reasoning-1",
          type: "reasoning",
          content: "## Plan\n\n- step 1",
          isFinished: true,
          createdAt: "2026-03-16T00:00:00.000Z",
          updatedAt: "2026-03-16T00:00:00.000Z",
        }}
        fallbackBlockId="fallback-1"
        messageId="message-1"
        onLayoutChangeStart={onLayoutChangeStart}
      />,
    );

    expect(mockMarkdownRender).not.toHaveBeenCalled();

    fireEvent.press(screen.getByLabelText("Show Reasoning"));

    await waitFor(() => {
      expect(mockMarkdownRender).toHaveBeenCalledWith({
        content: "## Plan\n\n- step 1",
        isAgent: true,
      });
    });
    expect(onLayoutChangeStart).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Show less")).toBeTruthy();
  });

  it("loads missing reasoning content before expanding", async () => {
    const onLoadBlockContent = jest.fn(async () => true);
    const screen = render(
      <ReasoningBlock
        block={{
          id: "",
          type: "reasoning",
          content: "",
          isFinished: false,
          createdAt: "2026-03-16T00:00:00.000Z",
          updatedAt: "2026-03-16T00:00:00.000Z",
        }}
        fallbackBlockId="fallback-2"
        messageId="message-2"
        onLoadBlockContent={onLoadBlockContent}
      />,
    );

    fireEvent.press(screen.getByLabelText("Show Reasoning"));

    await waitFor(() => {
      expect(onLoadBlockContent).toHaveBeenCalledWith(
        "message-2",
        "fallback-2",
      );
    });
  });
});
