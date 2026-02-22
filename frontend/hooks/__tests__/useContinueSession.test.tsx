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
  const chatHref = {
    pathname: "/(app)/chat/[agentId]/[conversationId]",
    params: { agentId: "agent-1", conversationId: "conversation-1" },
  };

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
    mockedBuildChatRoute.mockReturnValue(chatHref as never);
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
    expect(mockEnsureSession).toHaveBeenCalledWith("conversation-1", "agent-1");
    expect(mockBindExternalSession).toHaveBeenCalledWith("conversation-1", {
      agentId: "agent-1",
      source: "manual",
      provider: "opencode",
      externalSessionId: "upstream-1",
      contextId: undefined,
    });
    expect(mockedBlurActiveElement).toHaveBeenCalledTimes(1);
    expect(mockedBuildChatRoute).toHaveBeenCalledWith(
      "agent-1",
      "conversation-1",
    );
    expect(mockPush).toHaveBeenCalledWith(chatHref);
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
});
