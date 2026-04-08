import { act, fireEvent, render } from "@testing-library/react-native";
import * as Clipboard from "expo-clipboard";
import React from "react";
import { create } from "react-test-renderer";

import { ChatMessageItem } from "@/components/chat/ChatMessageItem";
import { type ChatMessage } from "@/lib/api/chat-utils";
import { toast } from "@/lib/toast";

jest.mock("@expo/vector-icons/Ionicons", () => () => null);

jest.mock("@/components/chat/MessageBlock", () => ({
  MessageBlock: () => {
    const { Text } = require("react-native");
    return <Text>Mocked Message Block</Text>;
  },
  MessageContentFallback: ({
    hasPlainContent,
    content,
  }: {
    hasPlainContent: boolean;
    content: string;
  }) => {
    const { Text } = require("react-native");
    return hasPlainContent ? (
      <Text>{content}</Text>
    ) : (
      <Text>Content unavailable.</Text>
    );
  },
}));

jest.mock("expo-clipboard", () => ({
  setStringAsync: jest.fn(),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const noopInterrupt = jest.fn();

const buildAgentMessage = (
  overrides: Partial<ChatMessage> = {},
): ChatMessage => ({
  id: "message-1",
  role: "agent",
  content: "Agent response",
  createdAt: "2026-02-24T00:00:00.000Z",
  status: "done",
  blocks: [],
  ...overrides,
});

describe("ChatMessageItem interaction", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("copies normalized agent content without duplicating block text", async () => {
    const message = buildAgentMessage({
      content: "Agent response",
      blocks: [
        {
          id: "block-1",
          type: "text",
          content: "Agent response",
          isFinished: true,
          createdAt: "2026-02-24T00:00:00.000Z",
          updatedAt: "2026-02-24T00:00:00.000Z",
        },
        {
          id: "block-2",
          type: "reasoning",
          content: "Internal reasoning",
          isFinished: true,
          createdAt: "2026-02-24T00:00:01.000Z",
          updatedAt: "2026-02-24T00:00:01.000Z",
        },
      ],
    });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onInterruptStream={noopInterrupt}
      />,
    );

    await act(async () => {
      fireEvent.press(screen.getByLabelText("Copy message"));
    });

    expect(Clipboard.setStringAsync).toHaveBeenCalledWith("Agent response");
    expect(Clipboard.setStringAsync).not.toHaveBeenCalledWith(
      expect.stringContaining("[text]"),
    );
    expect(Clipboard.setStringAsync).not.toHaveBeenCalledWith(
      expect.stringContaining("Internal reasoning"),
    );
  });

  it("copies message content to clipboard on copy button press", async () => {
    const message = buildAgentMessage({
      role: "user",
      content: "Copy via button",
    });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onInterruptStream={noopInterrupt}
      />,
    );

    await act(async () => {
      fireEvent.press(screen.getByLabelText("Copy message"));
    });

    expect(Clipboard.setStringAsync).toHaveBeenCalledWith("Copy via button");
    expect(toast.success).toHaveBeenCalledWith("Copied", expect.any(String));
  });

  it("shows retry button and calls onRetry when session status is error", () => {
    const onRetry = jest.fn();
    const message = buildAgentMessage({ role: "agent" });

    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={onRetry}
        sessionStreamState="error"
        onInterruptStream={noopInterrupt}
      />,
    );

    const retryButton = screen.getByText("Retry");
    expect(retryButton).toBeTruthy();
    fireEvent.press(retryButton);
    expect(onRetry).toHaveBeenCalled();
  });

  it("shows streaming indicator when status is streaming", () => {
    const message = buildAgentMessage({ status: "streaming" });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onInterruptStream={noopInterrupt}
      />,
    );

    expect(screen.getByText("Streaming...")).toBeTruthy();
  });

  it("keeps agent streaming bubbles at a stable width shell", () => {
    const message = buildAgentMessage({
      content: "",
      status: "streaming",
      blocks: [],
    });
    let root: ReturnType<typeof create> | null = null;

    act(() => {
      root = create(
        <ChatMessageItem
          message={message}
          index={0}
          isLastMessage
          onRetry={jest.fn()}
          onInterruptStream={noopInterrupt}
        />,
      );
    });

    const bubble = root!.root.find(
      (node) =>
        typeof node.props.className === "string" &&
        node.props.className.includes("rounded-2xl shadow-sm"),
    );

    expect(bubble.props.className).toContain("w-full");
    expect(bubble.props.className).toContain("min-h-[52px]");
  });

  it("copies message content on long press", async () => {
    const message = buildAgentMessage({
      role: "user",
      content: "Copy via long press",
    });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onInterruptStream={noopInterrupt}
      />,
    );

    await act(async () => {
      fireEvent(screen.getByText("Copy via long press"), "onLongPress");
    });

    expect(Clipboard.setStringAsync).toHaveBeenCalledWith(
      "Copy via long press",
    );
    expect(toast.success).toHaveBeenCalledWith(
      "Copied",
      "Message copied to clipboard.",
    );
  });

  it("does not copy block-only agent messages when normalized content is empty", async () => {
    const message = buildAgentMessage({
      content: "",
      blocks: [
        {
          id: "block-1",
          type: "text",
          content: "Primary text",
          isFinished: true,
          createdAt: "2026-02-24T00:00:00.000Z",
          updatedAt: "2026-02-24T00:00:00.000Z",
        },
        {
          id: "block-2",
          type: "tool_call",
          content: '{"tool":"search"}',
          isFinished: true,
          createdAt: "2026-02-24T00:00:01.000Z",
          updatedAt: "2026-02-24T00:00:01.000Z",
        },
      ],
    });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onInterruptStream={noopInterrupt}
      />,
    );

    await act(async () => {
      fireEvent.press(screen.getByLabelText("Copy message"));
    });

    expect(Clipboard.setStringAsync).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("does not show empty fallback while agent message is streaming without content", () => {
    const message = buildAgentMessage({
      content: "",
      status: "streaming",
      blocks: [],
    });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onInterruptStream={noopInterrupt}
      />,
    );

    expect(screen.queryByText("Content unavailable.")).toBeNull();
    expect(screen.getByText("Streaming...")).toBeTruthy();
  });

  it("renders a structured upstream error banner without empty fallback", () => {
    const message = buildAgentMessage({
      content: "",
      status: "error",
      errorCode: "agent_unavailable",
      errorMessage: "Upstream agent is unavailable.",
      blocks: [],
    });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        sessionStreamState="error"
        onInterruptStream={noopInterrupt}
      />,
    );

    expect(screen.queryByText("Content unavailable.")).toBeNull();
    expect(
      screen.getByText("Unable to reach the upstream agent. Please try again."),
    ).toBeTruthy();
  });

  it("renders missing parameter details for structured upstream stream errors", () => {
    const message = buildAgentMessage({
      content: "",
      status: "error",
      errorCode: "invalid_params",
      errorMessage:
        "Missing required upstream parameters: project_id, channel_id",
      errorSource: "upstream_a2a",
      jsonrpcCode: -32602,
      missingParams: [
        { name: "project_id", required: true },
        { name: "channel_id", required: true },
      ],
      upstreamError: { message: "project_id/channel_id required" },
      blocks: [],
    });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        sessionStreamState="error"
        onInterruptStream={noopInterrupt}
      />,
    );

    expect(
      screen.getByText(
        "Missing required upstream parameters: project_id, channel_id",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText("Streaming response failed. Please try again."),
    ).toBeNull();
  });

  it("shows interrupt button on a streaming agent message and calls handler", () => {
    const onInterruptStream = jest.fn();
    const message = buildAgentMessage({
      status: "streaming",
    });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage={false}
        onRetry={jest.fn()}
        onInterruptStream={onInterruptStream}
        sessionStreamState="streaming"
      />,
    );

    fireEvent.press(screen.getByTestId("chat-interrupt-button"));

    expect(onInterruptStream).toHaveBeenCalledTimes(1);
  });
});
