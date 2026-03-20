import { fireEvent, render, waitFor } from "@testing-library/react-native";
import React, { useState } from "react";

import { ToolCallBlock } from "../blocks/ToolCallBlock";

describe("ToolCallBlock", () => {
  it("renders completed tool calls as structured detail instead of raw payload text", async () => {
    const rawPayload =
      '{"call_id":"call-1","tool":"bash","status":"pending","input":{}}' +
      '{"call_id":"call-1","tool":"bash","status":"running",' +
      '"input":{"command":"pwd","description":"Inspect repository state."}}' +
      '{"call_id":"call-1","tool":"bash","status":"completed",' +
      '"title":"Inspect repository state.","output":"main\\nclean"}';

    const screen = render(
      <ToolCallBlock
        block={{
          id: "tool-call-1",
          type: "tool_call",
          content: rawPayload,
          isFinished: true,
          toolCall: {
            name: "bash",
            status: "success",
            callId: "call-1",
            arguments: {
              command: "pwd",
              description: "Inspect repository state.",
            },
            result: "main\nclean",
          },
          toolCallDetail: {
            name: "bash",
            status: "success",
            callId: "call-1",
            title: "Inspect repository state.",
            arguments: {
              command: "pwd",
              description: "Inspect repository state.",
            },
            result: "main\nclean",
            timeline: [
              { status: "pending", input: {} },
              {
                status: "running",
                title: "Inspect repository state.",
                input: {
                  command: "pwd",
                  description: "Inspect repository state.",
                },
              },
              {
                status: "completed",
                title: "Inspect repository state.",
                output: "main\nclean",
              },
            ],
            raw: rawPayload,
          },
          createdAt: "2026-03-19T00:00:00.000Z",
          updatedAt: "2026-03-19T00:00:00.000Z",
        }}
        fallbackBlockId="fallback-tool-call-1"
        messageId="message-1"
      />,
    );

    expect(screen.getByText("Show Tool Call Success")).toBeTruthy();

    fireEvent.press(screen.getByLabelText("Show Tool Call Success"));

    await waitFor(() => {
      expect(screen.getByText("bash")).toBeTruthy();
      expect(screen.getAllByText("Inspect repository state.").length).toBe(3);
      expect(screen.getByText("call_id: call-1")).toBeTruthy();
      expect(screen.getByText("Input")).toBeTruthy();
      expect(screen.getByText("Progress")).toBeTruthy();
      expect(screen.getByText("Result")).toBeTruthy();
      expect(screen.getByText("Pending")).toBeTruthy();
      expect(screen.getByText("Running")).toBeTruthy();
      expect(screen.getByText("Completed")).toBeTruthy();
      expect(screen.getByText("Command")).toBeTruthy();
      expect(screen.getByText("pwd")).toBeTruthy();
      expect(
        screen.getByText('{\n  "description": "Inspect repository state."\n}'),
      ).toBeTruthy();
      expect(screen.getByText("main\nclean")).toBeTruthy();
    });

    expect(screen.queryByText(rawPayload)).toBeNull();

    fireEvent.press(screen.getByLabelText("Show Raw Payload"));

    await waitFor(() => {
      expect(screen.getByText(rawPayload)).toBeTruthy();
    });
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

    expect(screen.getByText("Show Tool Call Interrupted")).toBeTruthy();
  });

  it("loads completed tool call detail before expanding even when raw content exists", async () => {
    const rawPayload =
      '{"call_id":"call-3","tool":"bash","status":"pending","input":{}}' +
      '{"call_id":"call-3","tool":"bash","status":"completed","output":"done"}';

    function TestHarness() {
      const [toolCallDetail, setToolCallDetail] = useState<{
        name?: string | null;
        status: "running" | "success" | "failed" | "interrupted" | "unknown";
        callId?: string | null;
        title?: string | null;
        arguments?: unknown;
        result?: unknown;
        timeline?: { status: string; title?: string | null }[];
        raw?: string | null;
      } | null>(null);

      return (
        <ToolCallBlock
          block={{
            id: "tool-call-3",
            type: "tool_call",
            content: rawPayload,
            isFinished: true,
            toolCall: {
              name: "bash",
              status: "success",
              callId: "call-3",
              arguments: { command: "pwd" },
              result: "done",
            },
            toolCallDetail,
            createdAt: "2026-03-19T00:00:00.000Z",
            updatedAt: "2026-03-19T00:00:00.000Z",
          }}
          fallbackBlockId="fallback-tool-call-3"
          messageId="message-3"
          onLoadBlockContent={async () => {
            setToolCallDetail({
              name: "bash",
              status: "success",
              callId: "call-3",
              title: "Inspect repository state.",
              arguments: {
                command: "pwd",
              },
              result: "done",
              timeline: [
                { status: "pending" },
                {
                  status: "completed",
                  title: "Inspect repository state.",
                },
              ],
              raw: rawPayload,
            });
            return true;
          }}
        />
      );
    }

    const screen = render(<TestHarness />);

    fireEvent.press(screen.getByLabelText("Show Tool Call Success"));

    await waitFor(() => {
      expect(screen.getAllByText("Inspect repository state.").length).toBe(2);
      expect(screen.getByText("Progress")).toBeTruthy();
      expect(screen.getByText("Completed")).toBeTruthy();
    });
  });
});
