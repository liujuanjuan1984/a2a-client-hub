import { fireEvent, render } from "@testing-library/react-native";

import { ChatMessageItem } from "@/components/chat/ChatMessageItem";
import { type ChatMessage } from "@/lib/api/chat-utils";

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
  content: "",
  createdAt: "2026-02-24T00:00:00.000Z",
  status: "done",
  blocks: [],
  ...overrides,
});

describe("ChatMessageItem collapsible blocks", () => {
  it("shows bottom collapse action for expanded reasoning block", () => {
    const onLayoutChangeStart = jest.fn();
    const message = buildAgentMessage({
      blocks: [
        {
          id: "reasoning-1",
          type: "reasoning",
          content: "internal thoughts",
          isFinished: true,
          createdAt: "2026-02-24T00:00:00.000Z",
          updatedAt: "2026-02-24T00:00:00.000Z",
        },
      ],
    });

    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onLayoutChangeStart={onLayoutChangeStart}
      />,
    );

    fireEvent.press(screen.getByText("Show Reasoning"));
    expect(
      screen.getByTestId("chat-message-reasoning-1-collapse-bottom"),
    ).toBeTruthy();

    fireEvent.press(
      screen.getByTestId("chat-message-reasoning-1-collapse-bottom"),
    );
    expect(onLayoutChangeStart).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Show Reasoning")).toBeTruthy();
  });

  it("shows bottom collapse action for expanded tool call block", () => {
    const onLayoutChangeStart = jest.fn();
    const message = buildAgentMessage({
      blocks: [
        {
          id: "tool-1",
          type: "tool_call",
          content: '{"name":"web.search"}',
          isFinished: true,
          createdAt: "2026-02-24T00:00:00.000Z",
          updatedAt: "2026-02-24T00:00:00.000Z",
        },
      ],
    });

    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onLayoutChangeStart={onLayoutChangeStart}
      />,
    );

    fireEvent.press(screen.getByText("Show Tool Call"));
    expect(
      screen.getByTestId("chat-message-tool-1-collapse-bottom"),
    ).toBeTruthy();

    fireEvent.press(screen.getByTestId("chat-message-tool-1-collapse-bottom"));
    expect(onLayoutChangeStart).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Show Tool Call")).toBeTruthy();
  });

  it("uses bottom collapse action for expanded long text content", () => {
    const onLayoutChangeStart = jest.fn();
    const message = buildAgentMessage({
      id: "plain-message",
      content: "A".repeat(600),
      blocks: [],
    });

    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onLayoutChangeStart={onLayoutChangeStart}
      />,
    );

    fireEvent.press(
      screen.getByTestId("chat-message-plain-message:text-expand"),
    );
    expect(
      screen.getByTestId("chat-message-plain-message:text-expand").props
        .accessibilityLabel,
    ).toBe("Collapse full text");
    expect(
      screen.getByTestId("chat-message-plain-message:text-collapse-bottom"),
    ).toBeTruthy();

    fireEvent.press(
      screen.getByTestId("chat-message-plain-message:text-collapse-bottom"),
    );
    expect(onLayoutChangeStart).toHaveBeenCalledTimes(2);
    expect(
      screen.getByTestId("chat-message-plain-message:text-expand"),
    ).toBeTruthy();
  });

  it("requests message blocks on demand when content is not loaded", () => {
    const onRequestMessageBlocks = jest.fn();
    const message = buildAgentMessage({
      id: "empty-agent-message",
      content: "",
      blocks: [],
    });

    const screen = render(
      <ChatMessageItem
        message={message}
        index={0}
        isLastMessage
        onRetry={jest.fn()}
        onRequestMessageBlocks={onRequestMessageBlocks}
      />,
    );

    fireEvent.press(
      screen.getByTestId("chat-message-empty-agent-message-load-content"),
    );
    expect(onRequestMessageBlocks).toHaveBeenCalledWith("empty-agent-message");
  });
});
