import { act, renderHook } from "@testing-library/react-native";

import { useContinueOpencodeSession } from "@/hooks/useContinueOpencodeSession";
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

describe("useContinueOpencodeSession", () => {
  const mockPush = jest.fn();
  const mockEnsureSession = jest.fn();
  const mockBindOpencodeSession = jest.fn();
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
          bindOpencodeSession: mockBindOpencodeSession,
        }),
    );
    mockedBuildChatRoute.mockReturnValue(chatHref as never);
  });

  it("returns false when session id is blank", async () => {
    const { result } = renderHook(() => useContinueOpencodeSession());

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
      source: "opencode",
      contextId: null,
      metadata: { foo: "bar", opencode_session_id: "upstream-1" },
    });

    const { result } = renderHook(() => useContinueOpencodeSession());

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
    expect(mockBindOpencodeSession).toHaveBeenCalledWith("session-1", {
      agentId: "agent-1",
      opencodeSessionId: "upstream-1",
      contextId: undefined,
      metadata: { foo: "bar", opencode_session_id: "upstream-1" },
    });
    expect(mockedBlurActiveElement).toHaveBeenCalledTimes(1);
    expect(mockedBuildChatRoute).toHaveBeenCalledWith("agent-1", "session-1");
    expect(mockPush).toHaveBeenCalledWith(chatHref);
  });

  it("returns false and shows toast when request fails", async () => {
    mockedContinueSession.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useContinueOpencodeSession());

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
