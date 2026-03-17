import { act, fireEvent, render } from "@testing-library/react-native";
import * as Clipboard from "expo-clipboard";
import React from "react";

import { ChatMessageItem } from "@/components/chat/ChatMessageItem";
import { type ChatMessage } from "@/lib/api/chat-utils";
import { toast } from "@/lib/toast";

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

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
      />,
    );

    expect(screen.getByText("Streaming...")).toBeTruthy();
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
      />,
    );

    expect(screen.queryByText("Content unavailable.")).toBeNull();
    expect(
      screen.getByText("当前无法连接到上游 Agent，请稍后重试。"),
    ).toBeTruthy();
  });
});
