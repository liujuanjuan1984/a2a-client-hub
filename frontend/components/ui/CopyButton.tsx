import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useCallback, useState } from "react";
import { Platform } from "react-native";

import { IconButton } from "./IconButton";

import { toast } from "@/lib/toast";

type IconButtonProps = React.ComponentProps<typeof IconButton>;

type CopyButtonProps = Omit<IconButtonProps, "icon" | "onPress"> & {
  value: string;
  idleIcon?: React.ComponentProps<typeof Ionicons>["name"];
  copiedIcon?: React.ComponentProps<typeof Ionicons>["name"];
  successMessage?: string;
  iconColor?: string;
};

export function CopyButton({
  value,
  idleIcon = "copy-outline",
  copiedIcon = "checkmark",
  successMessage = "Copied to clipboard",
  iconColor,
  ...props
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    if (!value) return;

    try {
      if (Platform.OS === "web" && typeof navigator !== "undefined") {
        if (navigator.clipboard?.writeText) {
          try {
            await navigator.clipboard.writeText(value);
          } catch {
            // Fall back to Expo clipboard API
            await Clipboard.setStringAsync(value);
          }
        } else {
          await Clipboard.setStringAsync(value);
        }
      } else {
        await Clipboard.setStringAsync(value);
      }

      setCopied(true);
      toast.success("Copied", successMessage);

      setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      toast.error("Copy failed", "Could not copy to clipboard");
    }
  }, [value, successMessage]);

  return (
    <IconButton
      {...props}
      icon={copied ? copiedIcon : idleIcon}
      onPress={handleCopy}
      iconColor={iconColor}
    />
  );
}
