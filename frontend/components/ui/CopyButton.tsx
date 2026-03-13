import * as Clipboard from "expo-clipboard";
import React, { useCallback, useEffect, useState } from "react";

import { IconButton } from "./IconButton";

import { toast } from "@/lib/toast";

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
    try {
      await Clipboard.setStringAsync(value);
      setCopied(true);
      toast.success("Copied", successMessage);
    } catch {
      toast.error("Copy failed", "Could not copy to clipboard.");
    }
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
