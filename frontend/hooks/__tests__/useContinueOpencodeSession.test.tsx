import { act, renderHook } from "@testing-library/react-native";

import { useContinueOpencodeSession } from "@/hooks/useContinueOpencodeSession";
import { continueOpencodeSession } from "@/lib/api/opencodeSessions";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/store/chat";

jest.mock("expo-router", () => ({
  useRouter: jest.fn(),
}));

jest.mock("@/lib/api/opencodeSessions", () => ({
  continueOpencodeSession: jest.fn(),
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

const mockedContinueOpencodeSession =
  continueOpencodeSession as jest.MockedFunction<
    typeof continueOpencodeSession
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
  const mockGenerateSessionId = jest.fn();
  const mockEnsureSession = jest.fn();
  const mockBindOpencodeSession = jest.fn();
  const chatHref = {
    pathname: "/(app)/chat/[agentId]/[sessionId]",
    params: { agentId: "agent-1", sessionId: "chat-1", opencodeSessionId: "s" },
  };

  beforeEach(() => {
    jest.clearAllMocks();
    useRouter.mockReturnValue({ push: mockPush });
    mockedUseChatStore.mockImplementation(
      (selector: (state: unknown) => unknown) =>
        selector({
          generateSessionId: mockGenerateSessionId,
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
    expect(mockedContinueOpencodeSession).not.toHaveBeenCalled();
    expect(mockedToast.error).toHaveBeenCalledWith(
      "Continue session failed",
      "Missing session id.",
    );
  });

  it("continues session and navigates to chat route", async () => {
    mockedContinueOpencodeSession.mockResolvedValue({
      contextId: null,
      metadata: { foo: "bar" },
      raw: {},
    });
    mockGenerateSessionId.mockReturnValue("chat-1");

    const { result } = renderHook(() => useContinueOpencodeSession());

    let ok = false;
    await act(async () => {
      ok = await result.current.continueSession({
        agentId: "agent-1",
        sessionId: "  session-1  ",
        source: "shared",
      });
    });

    expect(ok).toBe(true);
    expect(mockedContinueOpencodeSession).toHaveBeenCalledWith(
      "agent-1",
      "session-1",
      { source: "shared" },
    );
    expect(mockEnsureSession).toHaveBeenCalledWith("chat-1", "agent-1");
    expect(mockBindOpencodeSession).toHaveBeenCalledWith("chat-1", {
      agentId: "agent-1",
      opencodeSessionId: "session-1",
      contextId: undefined,
      metadata: { foo: "bar" },
    });
    expect(mockedBlurActiveElement).toHaveBeenCalledTimes(1);
    expect(mockedBuildChatRoute).toHaveBeenCalledWith("agent-1", "chat-1", {
      opencodeSessionId: "session-1",
    });
    expect(mockPush).toHaveBeenCalledWith(chatHref);
  });

  it("returns false and shows toast when request fails", async () => {
    mockedContinueOpencodeSession.mockRejectedValue(new Error("network down"));

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
