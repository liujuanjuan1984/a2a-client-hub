import { fireEvent, render, waitFor } from "@testing-library/react-native";

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

const buildUserMessage = (
  overrides: Partial<ChatMessage> = {},
): ChatMessage => ({
  id: "user-message-1",
  role: "user",
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
    expect(screen.queryByText("Show Tool Call")).toBeNull();
    expect(
      screen.getByTestId("chat-message-tool-1-collapse-bottom"),
    ).toBeTruthy();

    fireEvent.press(screen.getByTestId("chat-message-tool-1-collapse-bottom"));
    expect(onLayoutChangeStart).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Show Tool Call")).toBeTruthy();
  });

  it("loads tool call content before expanding when block content is empty", async () => {
    const onLayoutChangeStart = jest.fn();
    const onLoadBlockContent = jest.fn(async () => false);
    const message = buildAgentMessage({
      blocks: [
        {
          id: "tool-empty",
          type: "tool_call",
          content: "",
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
        onLoadBlockContent={onLoadBlockContent}
      />,
    );

    fireEvent.press(screen.getByText("Show Tool Call"));

    await waitFor(() => {
      expect(onLoadBlockContent).toHaveBeenCalledWith(
        "message-1",
        "tool-empty",
      );
    });
    expect(onLayoutChangeStart).not.toHaveBeenCalled();
  });

  it("expands after tool call content is loaded", async () => {
    const onLayoutChangeStart = jest.fn();
    const onLoadBlockContent = jest.fn(async () => true);
    const message = buildAgentMessage({
      blocks: [
        {
          id: "tool-empty",
          type: "tool_call",
          content: "",
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
        onLoadBlockContent={onLoadBlockContent}
      />,
    );

    fireEvent.press(screen.getByText("Show Tool Call"));

    await waitFor(() => {
      expect(onLoadBlockContent).toHaveBeenCalledWith(
        "message-1",
        "tool-empty",
      );
      expect(onLayoutChangeStart).toHaveBeenCalled();
    });
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
      screen.queryByTestId("chat-message-plain-message:text-expand"),
    ).toBeNull();
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

  it("shows placeholder when agent content is unavailable", () => {
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
      />,
    );

    expect(screen.getByText("Content unavailable.")).toBeTruthy();
  });

  it("shows placeholder when user content is unavailable", () => {
    const message = buildUserMessage({
      id: "empty-user-message",
      content: "",
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

    expect(screen.getByText("Content unavailable.")).toBeTruthy();
  });
});
