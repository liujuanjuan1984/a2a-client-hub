import { act, renderHook } from "@testing-library/react-native";

import { useChatComposerController } from "@/hooks/useChatComposerController";
import { toast } from "@/lib/toast";

jest.mock("@/lib/toast", () => ({
  toast: {
    info: jest.fn(),
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockedToast = toast as jest.Mocked<typeof toast>;

describe("useChatComposerController", () => {
  const ensureSession = jest.fn();
  const sendMessage = jest.fn();
  const setSharedModelSelection = jest.fn();
  const onAfterSend = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  const renderComposer = () =>
    renderHook(() =>
      useChatComposerController({
        activeAgentId: "agent-1",
        conversationId: "conv-1",
        agentSource: "personal",
        pendingInterruptActive: false,
        ensureSession,
        sendMessage,
        setSharedModelSelection,
        onAfterSend,
      }),
    );

  it("captures the latest draft when opening the shortcut manager", () => {
    const { result } = renderComposer();

    act(() => {
      result.current.handleInputChange("  summarize this diff  ");
      result.current.openShortcutManager();
    });

    expect(result.current.showShortcutManager).toBe(true);
    expect(result.current.shortcutManagerInitialPrompt).toBe(
      "  summarize this diff  ",
    );
  });

  it("replaces the draft when a shortcut is used", () => {
    const { result } = renderComposer();

    act(() => {
      result.current.openShortcutManager();
      result.current.handleUseShortcut("Use the cached prompt");
    });

    expect(result.current.showShortcutManager).toBe(false);
    expect(result.current.inputDefaultValue).toBe("Use the cached prompt");
    expect(result.current.hasInput).toBe(true);
    expect(result.current.hasSendableInput).toBe(true);
    expect(result.current.inputResetKey).toBe(1);
  });

  it("sends the current draft from the ref-backed buffer and clears the composer", () => {
    const { result } = renderComposer();

    act(() => {
      result.current.handleInputChange("Ship the patch");
      result.current.handleSend();
    });

    expect(sendMessage).toHaveBeenCalledWith(
      "conv-1",
      "agent-1",
      "Ship the patch",
      "personal",
    );
    expect(onAfterSend).toHaveBeenCalledTimes(1);
    expect(result.current.inputDefaultValue).toBe("");
    expect(result.current.hasInput).toBe(false);
    expect(result.current.hasSendableInput).toBe(false);
  });

  it("shows a toast once when the hard input limit is reached", () => {
    const { result } = renderComposer();
    const oversizedInput = "x".repeat(50_000);

    act(() => {
      result.current.handleInputChange(oversizedInput);
      result.current.handleInputChange(oversizedInput);
    });

    expect(mockedToast.info).toHaveBeenCalledTimes(1);
    expect(mockedToast.info).toHaveBeenCalledWith(
      "Message too long",
      "Messages are limited to 50,000 characters.",
    );
  });
});
