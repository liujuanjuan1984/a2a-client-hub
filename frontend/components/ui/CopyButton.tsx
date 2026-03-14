import React, { useCallback, useEffect, useState } from "react";

import { IconButton } from "./IconButton";

import { copyTextToClipboard, isCopyableText } from "@/lib/clipboard";

type CopyButtonProps = Omit<
  React.ComponentProps<typeof IconButton>,
  "icon" | "onPress"
> & {
  value: string;
  successMessage?: string;
  errorMessage?: string;
  successTitle?: string;
  errorTitle?: string;
};

export function CopyButton({
  value,
  successMessage = "Copied to clipboard.",
  errorMessage = "Could not copy to clipboard.",
  accessibilityLabel = "Copy to clipboard",
  successTitle,
  errorTitle,
  disabled,
  ...props
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const canCopy = isCopyableText(value);

  useEffect(() => {
    if (copied) {
      const timer = setTimeout(() => {
        setCopied(false);
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [copied]);

  const handleCopy = useCallback(async () => {
    if (!canCopy) return;

    await copyTextToClipboard(value, {
      successMessage,
      errorMessage,
      successTitle,
      errorTitle,
      onSuccess: () => setCopied(true),
    });
  }, [canCopy, errorMessage, errorTitle, successMessage, successTitle, value]);

  return (
    <IconButton
      icon={copied ? "checkmark" : "copy-outline"}
      accessibilityLabel={accessibilityLabel}
      onPress={handleCopy}
      disabled={disabled || !canCopy}
      {...props}
    />
  );
}
