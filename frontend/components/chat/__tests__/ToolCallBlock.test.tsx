import { fireEvent, render, waitFor } from "@testing-library/react-native";
import React, { useState } from "react";

import { ToolCallBlock } from "../blocks/ToolCallBlock";

describe("ToolCallBlock", () => {
  it("renders normalized tool call name and status, then expands arguments", async () => {
    const screen = render(
      <ToolCallBlock
        block={{
          id: "tool-call-1",
          type: "tool_call",
          content: "",
          isFinished: true,
          toolCall: {
            name: "bash",
            status: "failed",
            callId: "call-1",
            arguments: { command: "pwd" },
            error: { message: "boom" },
          },
          createdAt: "2026-03-19T00:00:00.000Z",
          updatedAt: "2026-03-19T00:00:00.000Z",
        }}
        fallbackBlockId="fallback-tool-call-1"
        messageId="message-1"
      />,
    );

    expect(screen.getByText("bash")).toBeTruthy();
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("call_id: call-1")).toBeTruthy();

    fireEvent.press(screen.getByLabelText("Show Tool Call"));

    await waitFor(() => {
      expect(screen.getByText('{\n  "command": "pwd"\n}')).toBeTruthy();
    });
    expect(screen.getByText('{\n  "message": "boom"\n}')).toBeTruthy();
  });

  it("falls back to message status when no normalized tool call status exists", () => {
    const screen = render(
      <ToolCallBlock
        block={{
          id: "tool-call-2",
          type: "tool_call",
          content: "",
          isFinished: false,
          createdAt: "2026-03-19T00:00:00.000Z",
          updatedAt: "2026-03-19T00:00:00.000Z",
        }}
        fallbackBlockId="fallback-tool-call-2"
        messageId="message-2"
        messageStatus="interrupted"
      />,
    );

    expect(screen.getByText("Interrupted")).toBeTruthy();
  });

  it("loads missing detail before expanding", async () => {
    function TestHarness() {
      const [content, setContent] = useState("");
      const [toolCall, setToolCall] = useState<{
        name?: string | null;
        status: "running" | "success" | "failed" | "interrupted" | "unknown";
        callId?: string | null;
        arguments?: unknown;
      } | null>(null);

      return (
        <ToolCallBlock
          block={{
            id: "tool-call-3",
            type: "tool_call",
            content,
            isFinished: false,
            toolCall,
            createdAt: "2026-03-19T00:00:00.000Z",
            updatedAt: "2026-03-19T00:00:00.000Z",
          }}
          fallbackBlockId="fallback-tool-call-3"
          messageId="message-3"
          onLoadBlockContent={async () => {
            setContent('{"tool":"read","input":{"path":"README.md"}}');
            setToolCall({
              name: "read",
              status: "running",
              arguments: { path: "README.md" },
            });
            return true;
          }}
        />
      );
    }

    const screen = render(<TestHarness />);

    fireEvent.press(screen.getByLabelText("Show Tool Call"));

    await waitFor(() => {
      expect(screen.getByText("read")).toBeTruthy();
    });
    expect(screen.getByText('{\n  "path": "README.md"\n}')).toBeTruthy();
  });
});
