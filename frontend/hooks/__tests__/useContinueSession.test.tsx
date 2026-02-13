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
    pathname: "/(app)/chat/[agentId]/[sessionId]",
    params: { agentId: "agent-1", sessionId: "session-1" },
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

  it("returns false when session id is blank", async () => {
    const { result } = renderHook(() => useContinueSession());

    let ok = true;
    await act(async () => {
      ok = await result.current.continueSession({
        agentId: "agent-1",
        sessionId: "   ",
      });
    });

    expect(ok).toBe(false);
    expect(mockedContinueSession).not.toHaveBeenCalled();
    expect(mockedToast.error).toHaveBeenCalledWith(
      "Continue session failed",
      "Missing session id.",
    );
  });

  it("continues session and navigates to chat route", async () => {
    mockedContinueSession.mockResolvedValue({
      session_id: "session-1",
      conversationId: "conv-1",
      source: "opencode",
      provider: "opencode",
      externalSessionId: "upstream-1",
      contextId: null,
      bindingMetadata: { mode: "continue" },
      metadata: { foo: "bar" },
    });

    const { result } = renderHook(() => useContinueSession());

    let ok = false;
    await act(async () => {
      ok = await result.current.continueSession({
        agentId: "agent-1",
        sessionId: "  session-1  ",
      });
    });

    expect(ok).toBe(true);
    expect(mockedContinueSession).toHaveBeenCalledWith("session-1");
    expect(mockEnsureSession).toHaveBeenCalledWith("session-1", "agent-1");
    expect(mockBindExternalSession).toHaveBeenCalledWith("session-1", {
      agentId: "agent-1",
      conversationId: "conv-1",
      provider: "opencode",
      externalSessionId: "upstream-1",
      contextId: undefined,
      bindingMetadata: { mode: "continue" },
      metadata: { foo: "bar" },
    });
    expect(mockedBlurActiveElement).toHaveBeenCalledTimes(1);
    expect(mockedBuildChatRoute).toHaveBeenCalledWith("agent-1", "session-1");
    expect(mockPush).toHaveBeenCalledWith(chatHref);
  });

  it("returns false and shows toast when request fails", async () => {
    mockedContinueSession.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useContinueSession());

    let ok = true;
    await act(async () => {
      ok = await result.current.continueSession({
        agentId: "agent-1",
        sessionId: "session-1",
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
