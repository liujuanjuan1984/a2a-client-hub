import { render } from "@testing-library/react-native";
import React from "react";

import { MessageBlock, MessageContentFallback } from "../MessageBlock";

import { type MessageBlock as MessageBlockType } from "@/lib/api/chat-utils";

const mockReasoningBlock = jest.fn((_props: unknown) => null);
const mockToolCallBlock = jest.fn((_props: unknown) => null);
const mockInterruptEventBlock = jest.fn((_props: unknown) => null);
const mockTextBlock = jest.fn((_props: unknown) => null);
const mockGenericBlock = jest.fn((_props: unknown) => null);

jest.mock("../blocks/ReasoningBlock", () => ({
  ReasoningBlock: (props: unknown) => {
    mockReasoningBlock(props);
    return null;
  },
}));

jest.mock("../blocks/ToolCallBlock", () => ({
  ToolCallBlock: (props: unknown) => {
    mockToolCallBlock(props);
    return null;
  },
}));

jest.mock("../blocks/InterruptEventBlock", () => ({
  InterruptEventBlock: (props: unknown) => {
    mockInterruptEventBlock(props);
    return null;
  },
}));

jest.mock("../blocks/TextBlock", () => ({
  TextBlock: (props: unknown) => {
    mockTextBlock(props);
    return null;
  },
}));

jest.mock("../blocks/GenericBlock", () => ({
  GenericBlock: (props: unknown) => {
    mockGenericBlock(props);
    return null;
  },
}));

describe("MessageBlock and MessageContentFallback", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("routes reasoning block to ReasoningBlock with expected props", () => {
    const block: MessageBlockType = {
      id: "reasoning-1",
      type: "reasoning",
      content: "internal thoughts",
      isFinished: true,
      createdAt: "2026-02-24T00:00:00.000Z",
      updatedAt: "2026-02-24T00:00:00.000Z",
    };

    const onLayoutChangeStart = jest.fn();
    const onLoadBlockContent = jest.fn(async () => true);

    render(
      <MessageBlock
        block={block}
        messageId="msg-1"
        blockIndex={0}
        role="agent"
        onLayoutChangeStart={onLayoutChangeStart}
        onLoadBlockContent={onLoadBlockContent}
      />,
    );

    expect(mockReasoningBlock).toHaveBeenCalledTimes(1);
    expect(mockReasoningBlock).toHaveBeenCalledWith(
      expect.objectContaining({
        block,
        fallbackBlockId: "reasoning-1",
        messageId: "msg-1",
        onLayoutChangeStart,
        onLoadBlockContent,
        isFirst: true,
      }),
    );
  });

  it("routes tool_call block to ToolCallBlock with generated fallback id", () => {
    const block: MessageBlockType = {
      id: "",
      type: "tool_call",
      content: "{}",
      isFinished: true,
      createdAt: "2026-02-24T00:00:00.000Z",
      updatedAt: "2026-02-24T00:00:00.000Z",
    };

    render(
      <MessageBlock
        block={block}
        messageId="msg-2"
        blockIndex={3}
        role="agent"
      />,
    );

    expect(mockToolCallBlock).toHaveBeenCalledTimes(1);
    expect(mockToolCallBlock).toHaveBeenCalledWith(
      expect.objectContaining({
        block,
        fallbackBlockId: "msg-2:3",
        messageId: "msg-2",
        isFirst: false,
      }),
    );
  });

  it("routes text block to TextBlock and maps role to isAgent", () => {
    const block: MessageBlockType = {
      id: "text-1",
      type: "text",
      content: "Hello",
      isFinished: true,
      createdAt: "2026-02-24T00:00:00.000Z",
      updatedAt: "2026-02-24T00:00:00.000Z",
    };

    render(
      <MessageBlock
        block={block}
        messageId="msg-3"
        blockIndex={1}
        role="user"
      />,
    );

    expect(mockTextBlock).toHaveBeenCalledTimes(1);
    expect(mockTextBlock).toHaveBeenCalledWith(
      expect.objectContaining({
        block,
        fallbackBlockId: "text-1",
        isAgent: false,
        isFirst: false,
      }),
    );
  });

  it("routes interrupt_event block to InterruptEventBlock", () => {
    const block: MessageBlockType = {
      id: "interrupt-1",
      type: "interrupt_event",
      content: "Agent requested authorization: read.",
      isFinished: true,
      createdAt: "2026-02-24T00:00:00.000Z",
      updatedAt: "2026-02-24T00:00:00.000Z",
    };

    render(
      <MessageBlock
        block={block}
        messageId="msg-3b"
        blockIndex={2}
        role="agent"
      />,
    );

    expect(mockInterruptEventBlock).toHaveBeenCalledTimes(1);
    expect(mockInterruptEventBlock).toHaveBeenCalledWith(
      expect.objectContaining({
        block,
        fallbackBlockId: "interrupt-1",
        isFirst: false,
      }),
    );
  });

  it("routes unknown block type to GenericBlock", () => {
    const block = {
      id: "generic-1",
      type: "artifact",
      content: "binary",
      isFinished: true,
      createdAt: "2026-02-24T00:00:00.000Z",
      updatedAt: "2026-02-24T00:00:00.000Z",
    } as MessageBlockType;

    render(
      <MessageBlock
        block={block}
        messageId="msg-4"
        blockIndex={0}
        role="agent"
      />,
    );

    expect(mockGenericBlock).toHaveBeenCalledTimes(1);
    expect(mockGenericBlock).toHaveBeenCalledWith(
      expect.objectContaining({
        block,
        fallbackBlockId: "generic-1",
        isFirst: true,
      }),
    );
  });

  it("renders fallback placeholder when plain content is unavailable", () => {
    const screen = render(
      <MessageContentFallback
        hasPlainContent={false}
        content=""
        messageId="msg-5"
        role="agent"
      />,
    );

    expect(screen.getByText("Content unavailable.")).toBeTruthy();
    expect(mockTextBlock).not.toHaveBeenCalled();
  });

  it("renders plain content through TextBlock when content exists", () => {
    render(
      <MessageContentFallback
        hasPlainContent
        content="Hello world"
        messageId="msg-6"
        role="agent"
      />,
    );

    expect(mockTextBlock).toHaveBeenCalledTimes(1);
    expect(mockTextBlock).toHaveBeenCalledWith(
      expect.objectContaining({
        content: "Hello world",
        fallbackBlockId: "msg-6",
        isAgent: true,
        isFirst: true,
      }),
    );
  });
});
