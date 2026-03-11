import { fireEvent, render, waitFor } from "@testing-library/react-native";
import React from "react";

import { MessageBlock, MessageContentFallback } from "../MessageBlock";

import { type MessageBlock as MessageBlockType } from "@/lib/api/chat-utils";

describe("MessageBlock and MessageContentFallback", () => {
  const onLayoutChangeStart = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders reasoning block and handles collapse", () => {
    const block: MessageBlockType = {
      id: "reasoning-1",
      type: "reasoning",
      content: "internal thoughts",
      isFinished: true,
      createdAt: "2026-02-24T00:00:00.000Z",
      updatedAt: "2026-02-24T00:00:00.000Z",
    };

    const screen = render(
      <MessageBlock
        block={block}
        messageId="msg-1"
        blockIndex={0}
        role="agent"
        onLayoutChangeStart={onLayoutChangeStart}
      />,
    );

    fireEvent.press(screen.getByText("Show Reasoning"));
    expect(screen.queryByText("Show Reasoning")).toBeNull();
    expect(
      screen.getByTestId("chat-message-reasoning-1-collapse-bottom"),
    ).toBeTruthy();

    fireEvent.press(
      screen.getByTestId("chat-message-reasoning-1-collapse-bottom"),
    );
    expect(onLayoutChangeStart).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Show Reasoning")).toBeTruthy();
  });

  it("renders tool call block and handles collapse", () => {
    const block: MessageBlockType = {
      id: "tool-1",
      type: "tool_call",
      content: '{"name":"web.search"}',
      isFinished: true,
      createdAt: "2026-02-24T00:00:00.000Z",
      updatedAt: "2026-02-24T00:00:00.000Z",
    };

    const screen = render(
      <MessageBlock
        block={block}
        messageId="msg-1"
        blockIndex={0}
        role="agent"
        onLayoutChangeStart={onLayoutChangeStart}
      />,
    );

    fireEvent.press(screen.getByText("Show Tool Call"));
    expect(screen.queryByText("Show Tool Call")).toBeNull();
    expect(
      screen.getByTestId("chat-message-tool-1-collapse-bottom"),
    ).toBeTruthy();

    fireEvent.press(screen.getByTestId("chat-message-tool-1-collapse-bottom"));
    expect(onLayoutChangeStart).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Show Tool Call")).toBeTruthy();
  });

  it("loads tool call content before expanding when empty", async () => {
    const onLoadBlockContentMock = jest.fn(async () => false);
    const block: MessageBlockType = {
      id: "tool-empty",
      type: "tool_call",
      content: "",
      isFinished: true,
      createdAt: "2026-02-24T00:00:00.000Z",
      updatedAt: "2026-02-24T00:00:00.000Z",
    };

    const screen = render(
      <MessageBlock
        block={block}
        messageId="msg-1"
        blockIndex={0}
        role="agent"
        onLoadBlockContent={onLoadBlockContentMock}
      />,
    );

    fireEvent.press(screen.getByText("Show Tool Call"));

    await waitFor(() => {
      expect(onLoadBlockContentMock).toHaveBeenCalledWith(
        "msg-1",
        "tool-empty",
      );
    });
  });

  it("expands tool call block after content load succeeds", async () => {
    const onLoadBlockContentMock = jest.fn(async () => true);
    const block: MessageBlockType = {
      id: "tool-expand-after-load",
      type: "tool_call",
      content: "",
      isFinished: true,
      createdAt: "2026-02-24T00:00:00.000Z",
      updatedAt: "2026-02-24T00:00:00.000Z",
    };

    const screen = render(
      <MessageBlock
        block={block}
        messageId="msg-1"
        blockIndex={0}
        role="agent"
        onLayoutChangeStart={onLayoutChangeStart}
        onLoadBlockContent={onLoadBlockContentMock}
      />,
    );

    fireEvent.press(screen.getByText("Show Tool Call"));

    await waitFor(() => {
      expect(onLoadBlockContentMock).toHaveBeenCalledWith(
        "msg-1",
        "tool-expand-after-load",
      );
      expect(onLayoutChangeStart).toHaveBeenCalled();
      expect(screen.getByLabelText("Hide Tool Call")).toBeTruthy();
    });
  });

  it("shows placeholder when content is unavailable", () => {
    const screen = render(
      <MessageContentFallback
        hasPlainContent={false}
        content=""
        messageId="msg-1"
        role="agent"
      />,
    );

    expect(screen.getByText("Content unavailable.")).toBeTruthy();
  });

  it("renders plain content using TextBlock", () => {
    const screen = render(
      <MessageContentFallback
        hasPlainContent
        content="Hello world"
        messageId="msg-1"
        role="user"
      />,
    );

    expect(screen.getByText("Hello world")).toBeTruthy();
  });
});
