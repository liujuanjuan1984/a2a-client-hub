import { fireEvent, render, waitFor } from "@testing-library/react-native";
import * as Clipboard from "expo-clipboard";
import React from "react";

import { ChatMessageItem } from "@/components/chat/ChatMessageItem";
import { type ChatMessage } from "@/lib/api/chat-utils";
import { toast } from "@/lib/toast";

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
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

  it("copies message content to clipboard on long press", async () => {
    const message = buildAgentMessage({ content: "Copy this text" });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
      />,
    );

    // Find the pressable area (container)
    fireEvent(screen.getByText("Copy this text"), "longPress");

    await waitFor(() => {
      expect(Clipboard.setStringAsync).toHaveBeenCalledWith("Copy this text");
      expect(toast.success).toHaveBeenCalledWith("Copied", expect.any(String));
    });
  });

  it("copies message content to clipboard on copy button press", async () => {
    const message = buildAgentMessage({ content: "Copy via button" });
    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
      />,
    );

    fireEvent.press(screen.getByLabelText("Copy message"));

    await waitFor(() => {
      expect(Clipboard.setStringAsync).toHaveBeenCalledWith("Copy via button");
      expect(toast.success).toHaveBeenCalledWith("Copied", expect.any(String));
    });
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
});
