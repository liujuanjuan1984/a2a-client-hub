import { act, renderHook } from "@testing-library/react-native";

import { useChatInterruptController } from "@/hooks/useChatInterruptController";
import {
  rejectQuestionInterrupt,
  replyPermissionInterrupt,
  replyQuestionInterrupt,
} from "@/lib/api/a2aExtensions";
import { toast } from "@/lib/toast";

jest.mock("@/lib/api/a2aExtensions", () => ({
  replyPermissionInterrupt: jest.fn(),
  replyQuestionInterrupt: jest.fn(),
  rejectQuestionInterrupt: jest.fn(),
  A2AExtensionCallError: class extends Error {},
}));

jest.mock("@/lib/api/client", () => ({
  ApiRequestError: class extends Error {
    errorCode: string | null = null;
    upstreamError: Record<string, unknown> | null = null;
  },
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockedReplyPermissionInterrupt = jest.mocked(replyPermissionInterrupt);
const mockedReplyQuestionInterrupt = jest.mocked(replyQuestionInterrupt);
const mockedRejectQuestionInterrupt = jest.mocked(rejectQuestionInterrupt);
const mockedToast = toast as jest.Mocked<typeof toast>;

describe("useChatInterruptController", () => {
  const clearPendingInterrupt = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    mockedReplyPermissionInterrupt.mockResolvedValue({
      ok: true,
      requestId: "perm-1",
    });
    mockedReplyQuestionInterrupt.mockResolvedValue({
      ok: true,
      requestId: "question-1",
    });
    mockedRejectQuestionInterrupt.mockResolvedValue({
      ok: true,
      requestId: "question-1",
    });
  });

  it("forwards opencode directory metadata with permission replies", async () => {
    const { result } = renderHook(() =>
      useChatInterruptController({
        activeAgentId: "agent-1",
        agentSource: "personal",
        conversationId: "conv-1",
        pendingInterrupt: {
          requestId: "perm-1",
          type: "permission",
          phase: "asked",
          details: { permission: "read", patterns: ["/workspace/**"] },
        },
        lastResolvedInterrupt: null,
        pendingQuestionCount: 0,
        sessionMetadata: {
          opencode: {
            directory: "/workspace/app",
          },
        },
        clearPendingInterrupt,
      }),
    );

    await act(async () => {
      result.current.handlePermissionReply("once");
      await Promise.resolve();
    });

    expect(mockedReplyPermissionInterrupt).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      requestId: "perm-1",
      reply: "once",
      metadata: {
        opencode: {
          directory: "/workspace/app",
        },
      },
    });
    expect(clearPendingInterrupt).toHaveBeenCalledWith("conv-1", "perm-1");
    expect(mockedToast.success).toHaveBeenCalledWith(
      "Action submitted",
      "Permission reply delivered to upstream.",
    );
  });

  it("forwards opencode directory metadata with question answers", async () => {
    const { result } = renderHook(() =>
      useChatInterruptController({
        activeAgentId: "agent-1",
        agentSource: "personal",
        conversationId: "conv-1",
        pendingInterrupt: {
          requestId: "question-1",
          type: "question",
          phase: "asked",
          details: {
            questions: [
              {
                header: null,
                question: "Proceed?",
                options: [],
              },
            ],
          },
        },
        lastResolvedInterrupt: null,
        pendingQuestionCount: 1,
        sessionMetadata: {
          opencode: {
            directory: "/workspace/app",
          },
        },
        clearPendingInterrupt,
      }),
    );

    act(() => {
      result.current.handleQuestionAnswerChange(0, "yes");
    });

    await act(async () => {
      result.current.handleQuestionReply();
      await Promise.resolve();
    });

    expect(mockedReplyQuestionInterrupt).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      requestId: "question-1",
      answers: [["yes"]],
      metadata: {
        opencode: {
          directory: "/workspace/app",
        },
      },
    });
    expect(clearPendingInterrupt).toHaveBeenCalledWith("conv-1", "question-1");
    expect(mockedToast.success).toHaveBeenCalledWith(
      "Action submitted",
      "Question answers delivered to upstream.",
    );
  });
});
