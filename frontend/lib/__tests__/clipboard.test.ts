import * as Clipboard from "expo-clipboard";

import { copyTextToClipboard } from "@/lib/clipboard";
import { toast } from "@/lib/toast";

jest.mock("@/lib/toast", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

describe("copyTextToClipboard", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("writes text with Expo clipboard and shows success toast", async () => {
    await expect(
      copyTextToClipboard("hello world", {
        successMessage: "Custom success",
      }),
    ).resolves.toBe(true);

    expect(Clipboard.setStringAsync).toHaveBeenCalledWith("hello world");
    expect(toast.success).toHaveBeenCalledWith("Copied", "Custom success");
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

    expect(toast.error).toHaveBeenCalledWith("Copy failed", "Custom error");
  });
});
