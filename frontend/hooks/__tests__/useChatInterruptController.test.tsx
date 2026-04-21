import { act, renderHook } from "@testing-library/react-native";

import { useChatInterruptController } from "@/hooks/useChatInterruptController";
import {
  rejectQuestionInterrupt,
  replyElicitationInterrupt,
  replyPermissionInterrupt,
  replyPermissionsInterrupt,
  replyQuestionInterrupt,
} from "@/lib/api/a2aExtensions";
import { ApiRequestError } from "@/lib/api/client";
import { toast } from "@/lib/toast";

jest.mock("@/lib/api/a2aExtensions", () => ({
  replyPermissionInterrupt: jest.fn(),
  replyPermissionsInterrupt: jest.fn(),
  replyQuestionInterrupt: jest.fn(),
  rejectQuestionInterrupt: jest.fn(),
  replyElicitationInterrupt: jest.fn(),
  A2AExtensionCallError: class extends Error {},
}));

jest.mock("@/lib/api/client", () => ({
  ApiRequestError: class extends Error {
    status: number;
    errorCode: string | null;
    source: string | null;
    jsonrpcCode: number | null;
    missingParams: { name: string; required: boolean }[] | null;
    upstreamError: Record<string, unknown> | null;

    constructor(
      message: string,
      status: number,
      options?: {
        errorCode?: string | null;
        source?: string | null;
        jsonrpcCode?: number | null;
        missingParams?: { name: string; required: boolean }[] | null;
        upstreamError?: Record<string, unknown> | null;
      },
    ) {
      super(message);
      this.name = "ApiRequestError";
      this.status = status;
      this.errorCode = options?.errorCode ?? null;
      this.source = options?.source ?? null;
      this.jsonrpcCode = options?.jsonrpcCode ?? null;
      this.missingParams = options?.missingParams ?? null;
      this.upstreamError = options?.upstreamError ?? null;
      Object.setPrototypeOf(this, new.target.prototype);
    }
  },
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    info: jest.fn(),
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockedReplyPermissionInterrupt = jest.mocked(replyPermissionInterrupt);
const mockedReplyPermissionsInterrupt = jest.mocked(replyPermissionsInterrupt);
const mockedReplyQuestionInterrupt = jest.mocked(replyQuestionInterrupt);
const mockedRejectQuestionInterrupt = jest.mocked(rejectQuestionInterrupt);
const mockedReplyElicitationInterrupt = jest.mocked(replyElicitationInterrupt);
const mockedToast = toast as jest.Mocked<typeof toast>;

describe("useChatInterruptController", () => {
  const clearPendingInterrupt = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    mockedReplyPermissionInterrupt.mockResolvedValue({
      ok: true,
      requestId: "perm-1",
    });
    mockedReplyPermissionsInterrupt.mockResolvedValue({
      ok: true,
      requestId: "perm-v2-1",
    });
    mockedReplyQuestionInterrupt.mockResolvedValue({
      ok: true,
      requestId: "question-1",
    });
    mockedRejectQuestionInterrupt.mockResolvedValue({
      ok: true,
      requestId: "question-1",
    });
    mockedReplyElicitationInterrupt.mockResolvedValue({
      ok: true,
      requestId: "eli-1",
    });
  });

  it("uses ack-fast semantics for permission grants after upstream ack", async () => {
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
        workingDirectory: "/workspace/app",
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
      workingDirectory: "/workspace/app",
    });
    expect(clearPendingInterrupt).toHaveBeenCalledWith("conv-1", "perm-1");
    expect(mockedToast.success).toHaveBeenCalledWith(
      "Action submitted",
      "Permission reply delivered to upstream.",
    );
  });

  it("keeps permission rejects transactional after upstream ack", async () => {
    const { result } = renderHook(() =>
      useChatInterruptController({
        activeAgentId: "agent-1",
        agentSource: "personal",
        conversationId: "conv-1",
        pendingInterrupt: {
          requestId: "perm-reject-1",
          type: "permission",
          phase: "asked",
          details: { permission: "write", patterns: ["/workspace/**"] },
        },
        lastResolvedInterrupt: null,
        pendingQuestionCount: 0,
        workingDirectory: "/workspace/app",
        clearPendingInterrupt,
      }),
    );

    await act(async () => {
      result.current.handlePermissionReply("reject");
      await Promise.resolve();
    });

    expect(mockedReplyPermissionInterrupt).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      requestId: "perm-reject-1",
      reply: "reject",
      workingDirectory: "/workspace/app",
    });
    expect(clearPendingInterrupt).toHaveBeenCalledWith(
      "conv-1",
      "perm-reject-1",
    );
    expect(mockedToast.success).toHaveBeenCalledWith(
      "Action submitted",
      "Permission reply delivered to upstream.",
    );
  });

  it("supports ack-fast permission reply overrides through the shared controller", async () => {
    const onPermissionReplyOverride = jest.fn().mockResolvedValue({
      mode: "ack-fast" as const,
      resolvedRequestId: "perm-override-1",
    });

    const { result } = renderHook(() =>
      useChatInterruptController({
        activeAgentId: "hub-assistant",
        agentSource: null,
        conversationId: "conv-1",
        pendingInterrupt: {
          requestId: "perm-override-1",
          type: "permission",
          phase: "asked",
          details: {
            permission: "write",
            patterns: ["hub_assistant.jobs.pause"],
          },
        },
        lastResolvedInterrupt: null,
        pendingQuestionCount: 0,
        clearPendingInterrupt,
        onPermissionReplyOverride,
        permissionReplySuccessMessage: "Authorization request handled.",
      }),
    );

    await act(async () => {
      result.current.handlePermissionReply("once");
      await Promise.resolve();
    });

    expect(onPermissionReplyOverride).toHaveBeenCalledWith({
      requestId: "perm-override-1",
      reply: "once",
    });
    expect(mockedReplyPermissionInterrupt).not.toHaveBeenCalled();
    expect(clearPendingInterrupt).toHaveBeenCalledWith(
      "conv-1",
      "perm-override-1",
    );
    expect(mockedToast.success).toHaveBeenCalledWith(
      "Action submitted",
      "Authorization request handled.",
    );
  });

  it("supports transactional permission reply overrides through the shared controller", async () => {
    const onPermissionReplyOverride = jest.fn().mockResolvedValue({
      mode: "transactional" as const,
      resolvedRequestId: "perm-override-2",
    });

    const { result } = renderHook(() =>
      useChatInterruptController({
        activeAgentId: "hub-assistant",
        agentSource: null,
        conversationId: "conv-1",
        pendingInterrupt: {
          requestId: "perm-original-2",
          type: "permission",
          phase: "asked",
          details: {
            permission: "write",
            patterns: ["hub_assistant.jobs.resume"],
          },
        },
        lastResolvedInterrupt: null,
        pendingQuestionCount: 0,
        clearPendingInterrupt,
        onPermissionReplyOverride,
        permissionReplySuccessMessage: "Authorization request handled.",
      }),
    );

    await act(async () => {
      result.current.handlePermissionReply("always");
      await Promise.resolve();
    });

    expect(onPermissionReplyOverride).toHaveBeenCalledWith({
      requestId: "perm-original-2",
      reply: "always",
    });
    expect(mockedReplyPermissionInterrupt).not.toHaveBeenCalled();
    expect(clearPendingInterrupt).toHaveBeenCalledWith(
      "conv-1",
      "perm-override-2",
    );
    expect(mockedToast.success).toHaveBeenCalledWith(
      "Action submitted",
      "Authorization request handled.",
    );
  });

  it("uses ack-fast semantics for question answers after upstream ack", async () => {
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
        workingDirectory: "/workspace/app",
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
      workingDirectory: "/workspace/app",
    });
    expect(clearPendingInterrupt).toHaveBeenCalledWith("conv-1", "question-1");
    expect(mockedToast.success).toHaveBeenCalledWith(
      "Action submitted",
      "Question answers delivered to upstream.",
    );
  });

  it("uses ack-fast semantics for scope-aware permissions replies", async () => {
    const { result } = renderHook(() =>
      useChatInterruptController({
        activeAgentId: "agent-1",
        agentSource: "personal",
        conversationId: "conv-1",
        pendingInterrupt: {
          requestId: "perm-v2-1",
          type: "permissions",
          phase: "asked",
          details: {
            permissions: {
              fileSystem: { write: ["/workspace/project"] },
            },
          },
        },
        lastResolvedInterrupt: null,
        pendingQuestionCount: 0,
        workingDirectory: "/workspace/app",
        clearPendingInterrupt,
      }),
    );

    await act(async () => {
      result.current.handlePermissionsReply("session");
      await Promise.resolve();
    });

    expect(mockedReplyPermissionsInterrupt).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      requestId: "perm-v2-1",
      permissions: {
        fileSystem: { write: ["/workspace/project"] },
      },
      scope: "session",
      workingDirectory: "/workspace/app",
    });
    expect(clearPendingInterrupt).toHaveBeenCalledWith("conv-1", "perm-v2-1");
  });

  it("keeps elicitation accept replies transactional", async () => {
    const { result } = renderHook(() =>
      useChatInterruptController({
        activeAgentId: "agent-1",
        agentSource: "personal",
        conversationId: "conv-1",
        pendingInterrupt: {
          requestId: "eli-1",
          type: "elicitation",
          phase: "asked",
          details: {
            displayMessage: "Select the target folder.",
            mode: "form",
          },
        },
        lastResolvedInterrupt: null,
        pendingQuestionCount: 0,
        workingDirectory: "/workspace/app",
        clearPendingInterrupt,
      }),
    );

    act(() => {
      result.current.handleStructuredResponseChange('{"folder":"docs"}');
    });

    await act(async () => {
      result.current.handleElicitationReply("accept");
      await Promise.resolve();
    });

    expect(mockedReplyElicitationInterrupt).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      requestId: "eli-1",
      action: "accept",
      content: { folder: "docs" },
      workingDirectory: "/workspace/app",
    });
    expect(clearPendingInterrupt).toHaveBeenCalledWith("conv-1", "eli-1");
  });

  it("clears stale permission interrupts when upstream reports expiration", async () => {
    mockedReplyPermissionInterrupt.mockRejectedValueOnce(
      new ApiRequestError("Conflict", 409, {
        errorCode: "interrupt_request_expired",
        upstreamError: { message: "Interrupt request expired" },
      }),
    );
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
        clearPendingInterrupt,
      }),
    );

    await act(async () => {
      result.current.handlePermissionReply("once");
      await Promise.resolve();
    });

    expect(clearPendingInterrupt).toHaveBeenCalledWith("conv-1", "perm-1");
    expect(mockedToast.info).toHaveBeenCalledWith(
      "Interrupt closed",
      "The interrupt request expired and was removed.",
    );
    expect(mockedToast.error).not.toHaveBeenCalled();
  });

  it("clears stale question reply interrupts when upstream reports not found", async () => {
    mockedReplyQuestionInterrupt.mockRejectedValueOnce(
      new ApiRequestError("Not Found", 404, {
        errorCode: "interrupt_request_not_found",
        upstreamError: { message: "Interrupt request not found" },
      }),
    );
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

    expect(clearPendingInterrupt).toHaveBeenCalledWith("conv-1", "question-1");
    expect(mockedToast.info).toHaveBeenCalledWith(
      "Interrupt closed",
      "The interrupt request no longer exists and was removed.",
    );
    expect(mockedToast.error).not.toHaveBeenCalled();
  });

  it("clears stale question reject interrupts when upstream reports expiration", async () => {
    mockedRejectQuestionInterrupt.mockRejectedValueOnce(
      new ApiRequestError("Conflict", 409, {
        errorCode: "interrupt_request_expired",
        upstreamError: { message: "Interrupt request expired" },
      }),
    );
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
        clearPendingInterrupt,
      }),
    );

    await act(async () => {
      result.current.handleQuestionReject();
      await Promise.resolve();
    });

    expect(clearPendingInterrupt).toHaveBeenCalledWith("conv-1", "question-1");
    expect(mockedToast.info).toHaveBeenCalledWith(
      "Interrupt closed",
      "The interrupt request expired and was removed.",
    );
    expect(mockedToast.error).not.toHaveBeenCalled();
  });

  it("keeps pending interrupts visible for non-terminal callback errors", async () => {
    mockedReplyPermissionInterrupt.mockRejectedValueOnce(
      new ApiRequestError("Bad Request", 400, {
        errorCode: "invalid_params",
        upstreamError: { message: "reply is invalid" },
      }),
    );
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
        clearPendingInterrupt,
      }),
    );

    await act(async () => {
      result.current.handlePermissionReply("once");
      await Promise.resolve();
    });

    expect(clearPendingInterrupt).not.toHaveBeenCalled();
    expect(mockedToast.info).not.toHaveBeenCalled();
    expect(mockedToast.error).toHaveBeenCalledWith(
      "Interrupt callback failed",
      "Bad Request [invalid_params]：reply is invalid",
    );
  });
});
