import * as Clipboard from "expo-clipboard";
import { Platform } from "react-native";

import { toast } from "@/lib/toast";

type CopyTextOptions = {
  successMessage?: string;
  errorMessage?: string;
  successTitle?: string;
  errorTitle?: string;
  onSuccess?: () => void;
  onError?: () => void;
};

async function writeClipboardText(value: string) {
  if (
    Platform.OS === "web" &&
    typeof navigator !== "undefined" &&
    navigator.clipboard?.writeText
  ) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Fall back to Expo clipboard API when browser clipboard access fails.
    }
  }

  await Clipboard.setStringAsync(value);
}

export async function copyTextToClipboard(
  value: string,
  {
    successMessage = "Copied to clipboard.",
    errorMessage = "Could not copy to clipboard.",
    successTitle = "Copied",
    errorTitle = "Copy failed",
    onSuccess,
    onError,
  }: CopyTextOptions = {},
) {
  try {
    await writeClipboardText(value);
    onSuccess?.();
    toast.success(successTitle, successMessage);
    return true;
  } catch {
    onError?.();
    toast.error(errorTitle, errorMessage);
    return false;
  }
}
