import * as Clipboard from "expo-clipboard";
import { Platform } from "react-native";

import { COPY_FEEDBACK_TITLES, copyTextToClipboard } from "@/lib/clipboard";
import { toast } from "@/lib/toast";

jest.mock("@/lib/toast", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

describe("copyTextToClipboard", () => {
  const originalPlatform = Platform.OS;
  const originalNavigator = global.navigator;

  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(Platform, "OS", {
      configurable: true,
      value: originalPlatform,
    });
    Object.defineProperty(global, "navigator", {
      configurable: true,
      value: originalNavigator,
    });
  });

  it("writes text with Expo clipboard and shows success toast", async () => {
    await expect(
      copyTextToClipboard("hello world", {
        successMessage: "Custom success",
      }),
    ).resolves.toBe(true);

    expect(Clipboard.setStringAsync).toHaveBeenCalledWith("hello world");
    expect(toast.success).toHaveBeenCalledWith(
      COPY_FEEDBACK_TITLES.success,
      "Custom success",
    );
  });

  it("shows error toast when clipboard write fails", async () => {
    jest
      .mocked(Clipboard.setStringAsync)
      .mockRejectedValueOnce(new Error("clipboard failed"));

    await expect(
      copyTextToClipboard("hello world", {
        errorMessage: "Custom error",
      }),
    ).resolves.toBe(false);

    expect(toast.error).toHaveBeenCalledWith(
      COPY_FEEDBACK_TITLES.error,
      "Custom error",
    );
  });

  it("returns false for blank text without touching the clipboard", async () => {
    await expect(copyTextToClipboard("   ")).resolves.toBe(false);

    expect(Clipboard.setStringAsync).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("uses navigator clipboard on web when available", async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(Platform, "OS", {
      configurable: true,
      value: "web",
    });
    Object.defineProperty(global, "navigator", {
      configurable: true,
      value: { clipboard: { writeText } },
    });

    await expect(copyTextToClipboard("from web")).resolves.toBe(true);

    expect(writeText).toHaveBeenCalledWith("from web");
    expect(Clipboard.setStringAsync).not.toHaveBeenCalled();
  });

  it("falls back to Expo clipboard when navigator clipboard fails", async () => {
    const writeText = jest.fn().mockRejectedValue(new Error("blocked"));
    Object.defineProperty(Platform, "OS", {
      configurable: true,
      value: "web",
    });
    Object.defineProperty(global, "navigator", {
      configurable: true,
      value: { clipboard: { writeText } },
    });

    await expect(copyTextToClipboard("fallback path")).resolves.toBe(true);

    expect(writeText).toHaveBeenCalledWith("fallback path");
    expect(Clipboard.setStringAsync).toHaveBeenCalledWith("fallback path");
  });
});
