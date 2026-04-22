import { apiRequest } from "@/lib/api/client";
import {
  appendSessionMessage,
  cancelSession,
  continueSession,
  getSessionUpstreamTask,
  runSessionCommand,
} from "@/lib/api/sessions";

jest.mock("@/lib/api/client", () => ({
  apiRequest: jest.fn(),
}));

const mockedApiRequest = apiRequest as jest.MockedFunction<typeof apiRequest>;

describe("sessions api", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("posts cancel session request to unified endpoint", async () => {
    mockedApiRequest.mockResolvedValue({
      conversationId: "conv-1",
      taskId: "task-1",
      cancelled: true,
      status: "accepted",
    });

    const result = await cancelSession("conv-1");

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/conversations/conv-1/cancel",
      {
        method: "POST",
      },
    );
    expect(result).toEqual({
      conversationId: "conv-1",
      taskId: "task-1",
      cancelled: true,
      status: "accepted",
    });
  });

  it("gets upstream task by conversation and task id", async () => {
    mockedApiRequest.mockResolvedValue({
      conversationId: "conv-1",
      taskId: "task-1",
      task: {
        id: "task-1",
        status: { state: "working" },
      },
    });

    const result = await getSessionUpstreamTask(" conv-1 ", " task-1 ", {
      historyLength: 3,
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/conversations/conv-1/upstream-tasks/task-1",
      {
        method: "GET",
        query: { historyLength: 3 },
      },
    );
    expect(result.task.status?.state).toBe("working");
  });

  it("rejects upstream task query without ids", async () => {
    await expect(getSessionUpstreamTask(" ", "task-1")).rejects.toThrow(
      "Conversation id is required.",
    );
    await expect(getSessionUpstreamTask("conv-1", " ")).rejects.toThrow(
      "Task id is required.",
    );
    expect(mockedApiRequest).not.toHaveBeenCalled();
  });

  it("normalizes continue session payload conversation id", async () => {
    mockedApiRequest.mockResolvedValue({
      conversationId: "  conv-2  ",
      source: "manual",
      metadata: { provider: "opencode" },
      workingDirectory: "  /workspace/app  ",
    });

    const result = await continueSession("conv-2");

    expect(result.conversationId).toBe("conv-2");
    expect(result.metadata).toEqual({ provider: "opencode" });
    expect(result.workingDirectory).toBe("/workspace/app");
  });

  it("posts append session message request to unified conversation endpoint", async () => {
    mockedApiRequest.mockResolvedValue({
      conversationId: "conv-3",
      userMessage: { id: "msg-user-1" },
      sessionControl: {
        intent: "append",
        status: "accepted",
        sessionId: "ses-1",
      },
    });

    await appendSessionMessage("conv-3", {
      content: "append this",
      userMessageId: "msg-user-1",
      operationId: "op-append-1",
      metadata: { shared: { stream: { turn_id: "turn-1" } } },
      workingDirectory: "/workspace/app",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/conversations/conv-3/messages:append",
      {
        method: "POST",
        body: {
          content: "append this",
          userMessageId: "msg-user-1",
          operationId: "op-append-1",
          metadata: { shared: { stream: { turn_id: "turn-1" } } },
          workingDirectory: "/workspace/app",
        },
      },
    );
  });

  it("posts run session command request to unified conversation endpoint", async () => {
    mockedApiRequest.mockResolvedValue({
      conversationId: "conv-4",
      userMessage: { id: "msg-user-2" },
      agentMessage: { id: "msg-agent-2" },
    });

    await runSessionCommand("conv-4", {
      command: "/review",
      arguments: "--quick",
      prompt: "Focus on tests",
      userMessageId: "msg-user-2",
      agentMessageId: "msg-agent-2",
      operationId: "op-command-1",
      metadata: { provider: "opencode" },
      workingDirectory: "/workspace/app",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/conversations/conv-4/commands:run",
      {
        method: "POST",
        body: {
          command: "/review",
          arguments: "--quick",
          prompt: "Focus on tests",
          userMessageId: "msg-user-2",
          agentMessageId: "msg-agent-2",
          operationId: "op-command-1",
          metadata: { provider: "opencode" },
          workingDirectory: "/workspace/app",
        },
      },
    );
  });
});
