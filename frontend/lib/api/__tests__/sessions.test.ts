import { apiRequest } from "@/lib/api/client";
import { cancelSession, continueSession } from "@/lib/api/sessions";

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
});
