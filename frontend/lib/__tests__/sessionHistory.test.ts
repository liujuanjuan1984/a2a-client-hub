import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";

describe("session history mapping", () => {
  it("hydrates reasoning and tool call content from opencode metadata", () => {
    const mapped = mapSessionMessagesToChatMessages(
      [
        {
          id: "msg-1",
          role: "assistant",
          content: "final",
          created_at: "2026-02-14T00:00:00.000Z",
          metadata: {
            opencode_stream: {
              reasoning: "thinking",
              tool_call: "run_tool()",
            },
          },
        },
      ],
      "session-1",
    );

    expect(mapped).toEqual([
      {
        id: "msg-1",
        role: "agent",
        content: "final",
        createdAt: "2026-02-14T00:00:00.000Z",
        status: "done",
        reasoningContent: "thinking",
        toolCallContent: "run_tool()",
      },
    ]);
  });

  it("supports camelCase metadata alias", () => {
    const mapped = mapSessionMessagesToChatMessages(
      [
        {
          id: "msg-2",
          role: "assistant",
          content: "final",
          created_at: "2026-02-14T00:00:01.000Z",
          metadata: {
            opencodeStream: {
              reasoning: "plan",
              toolCall: "call()",
            },
          },
        },
      ],
      "session-2",
    );

    expect(mapped[0]?.reasoningContent).toBe("plan");
    expect(mapped[0]?.toolCallContent).toBe("call()");
  });
});
