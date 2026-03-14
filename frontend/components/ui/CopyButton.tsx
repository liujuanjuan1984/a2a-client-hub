import React, { useCallback, useEffect, useState } from "react";

import { IconButton } from "./IconButton";

import { copyTextToClipboard } from "@/lib/clipboard";

type CopyButtonProps = Omit<
  React.ComponentProps<typeof IconButton>,
  "icon" | "onPress"
> & {
  value: string;
  successMessage?: string;
};

export function CopyButton({
  value,
  successMessage = "Copied to clipboard.",
  accessibilityLabel = "Copy to clipboard",
  ...props
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (copied) {
      const timer = setTimeout(() => {
        setCopied(false);
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [copied]);

  const handleCopy = useCallback(async () => {
    await copyTextToClipboard(value, {
      successMessage,
      onSuccess: () => setCopied(true),
    });
  }, [value, successMessage]);

  return (
    <IconButton
      icon={copied ? "checkmark" : "copy-outline"}
      accessibilityLabel={accessibilityLabel}
      onPress={handleCopy}
      {...props}
    />
  );
}
