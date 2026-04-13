import { act, renderHook } from "@testing-library/react-native";

import { useContinueSession } from "@/hooks/useContinueSession";
import { continueSession } from "@/lib/api/sessions";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/store/chat";

jest.mock("expo-router", () => ({
  useRouter: jest.fn(),
}));

jest.mock("@/lib/api/sessions", () => ({
  continueSession: jest.fn(),
}));

jest.mock("@/lib/focus", () => ({
  blurActiveElement: jest.fn(),
}));

jest.mock("@/lib/routes", () => ({
  buildChatRoute: jest.fn(),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    error: jest.fn(),
  },
}));

jest.mock("@/store/chat", () => ({
  useChatStore: jest.fn(),
}));

const { useRouter } = jest.requireMock("expo-router") as {
  useRouter: jest.Mock;
};

const mockedContinueSession = continueSession as jest.MockedFunction<
  typeof continueSession
>;
const mockedBlurActiveElement = blurActiveElement as jest.MockedFunction<
  typeof blurActiveElement
>;
const mockedBuildChatRoute = buildChatRoute as jest.MockedFunction<
  typeof buildChatRoute
>;
const mockedToast = toast as jest.Mocked<typeof toast>;
const mockedUseChatStore = useChatStore as unknown as jest.Mock;

describe("useContinueSession", () => {
  const mockPush = jest.fn();
  const mockEnsureSession = jest.fn();
  const mockBindExternalSession = jest.fn();
  beforeEach(() => {
    jest.clearAllMocks();
    useRouter.mockReturnValue({ push: mockPush });
    mockedUseChatStore.mockImplementation(
      (selector: (state: unknown) => unknown) =>
        selector({
          ensureSession: mockEnsureSession,
          bindExternalSession: mockBindExternalSession,
        }),
    );
    mockedBuildChatRoute.mockImplementation(
      (agentId, conversationId) =>
        ({
          pathname: "/(app)/chat/[agentId]/[conversationId]",
          params: { agentId, conversationId },
        }) as never,
    );
  });

  it("returns false when conversation id is blank", async () => {
    const { result } = renderHook(() => useContinueSession());

    let ok = true;
    await act(async () => {
      ok = await result.current.continueSession({
        agentId: "agent-1",
        conversationId: "   ",
      });
    });

    expect(ok).toBe(false);
    expect(mockedContinueSession).not.toHaveBeenCalled();
    expect(mockedToast.error).toHaveBeenCalledWith(
      "Continue session failed",
      "Missing conversation id.",
    );
  });

  it("continues conversation and navigates to chat route", async () => {
    mockedContinueSession.mockResolvedValue({
      conversationId: "conv-1",
      source: "manual",
      metadata: {
        provider: "opencode",
        externalSessionId: "upstream-1",
      },
      workingDirectory: "/workspace/app",
    });

    const { result } = renderHook(() => useContinueSession());

    let ok = false;
    await act(async () => {
      ok = await result.current.continueSession({
        agentId: "agent-1",
        conversationId: "  conversation-1  ",
      });
    });

    expect(ok).toBe(true);
    expect(mockedContinueSession).toHaveBeenCalledWith("conversation-1");
    expect(mockEnsureSession).toHaveBeenCalledWith("conv-1", "agent-1", {
      createdAt: undefined,
      lastActiveAt: undefined,
    });
    expect(mockBindExternalSession).toHaveBeenCalledWith("conv-1", {
      agentId: "agent-1",
      source: "manual",
      provider: "opencode",
      externalSessionId: "upstream-1",
      workingDirectory: "/workspace/app",
    });
    expect(mockedBlurActiveElement).toHaveBeenCalledTimes(1);
    expect(mockedBuildChatRoute).toHaveBeenCalledWith("agent-1", "conv-1");
    expect(mockPush).toHaveBeenCalledWith({
      pathname: "/(app)/chat/[agentId]/[conversationId]",
      params: { agentId: "agent-1", conversationId: "conv-1" },
    });
  });

  it("navigates to rebound conversation id from backend", async () => {
    mockedContinueSession.mockResolvedValue({
      conversationId: "rebound-conversation-id",
      source: "manual",
      metadata: {
        provider: "opencode",
        externalSessionId: "upstream-1",
      },
      workingDirectory: "/workspace/app",
    });
    const { result } = renderHook(() => useContinueSession());
    let ok = false;
    await act(async () => {
      ok = await result.current.continueSession({
        agentId: "agent-1",
        conversationId: "  conversation-1  ",
      });
    });

    const reboundedHref = {
      pathname: "/(app)/chat/[agentId]/[conversationId]",
      params: { agentId: "agent-1", conversationId: "rebound-conversation-id" },
    };
    expect(ok).toBe(true);
    expect(mockedContinueSession).toHaveBeenCalledWith("conversation-1");
    expect(mockEnsureSession).toHaveBeenCalledWith(
      "rebound-conversation-id",
      "agent-1",
      {
        createdAt: undefined,
        lastActiveAt: undefined,
      },
    );
    expect(mockBindExternalSession).toHaveBeenCalledWith(
      "rebound-conversation-id",
      {
        agentId: "agent-1",
        source: "manual",
        provider: "opencode",
        externalSessionId: "upstream-1",
        workingDirectory: "/workspace/app",
      },
    );
    expect(mockedBuildChatRoute).toHaveBeenCalledWith(
      "agent-1",
      "rebound-conversation-id",
    );
    expect(mockPush).toHaveBeenCalledWith(reboundedHref);
  });

  it("returns false and shows toast when request fails", async () => {
    mockedContinueSession.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useContinueSession());

    let ok = true;
    await act(async () => {
      ok = await result.current.continueSession({
        agentId: "agent-1",
        conversationId: "conversation-1",
      });
    });

    expect(ok).toBe(false);
    expect(mockedToast.error).toHaveBeenCalledWith(
      "Continue session failed",
      "network down",
    );
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("shows semantic message when continue session is forbidden", async () => {
    const forbiddenError = new Error(
      "Request failed (403) [session_forbidden]",
    );
    Object.assign(forbiddenError, { errorCode: "session_forbidden" });
    mockedContinueSession.mockRejectedValue(forbiddenError);

    const { result } = renderHook(() => useContinueSession());

    let ok = true;
    await act(async () => {
      ok = await result.current.continueSession({
        agentId: "agent-1",
        conversationId: "conversation-1",
      });
    });

    expect(ok).toBe(false);
    expect(mockedToast.error).toHaveBeenCalledWith(
      "Continue session failed",
      "You do not have permission to continue this session.",
    );
    expect(mockPush).not.toHaveBeenCalled();
  });
});
