import { useRouter } from "expo-router";
import React from "react";

import { IconButton } from "@/components/ui/IconButton";
import { blurActiveElement } from "@/lib/focus";
import { backOrHome } from "@/lib/navigation";

type BackButtonProps = {
  /**
   * Optional fallback path if cannot go back.
   */
  fallbackPath?: string;
  /**
   * Optional variant for the IconButton. Defaults to "secondary".
   */
  variant?: "primary" | "outline" | "ghost" | "danger" | "secondary";
  /**
   * Optional size for the IconButton. Defaults to "sm".
   */
  size?: "xs" | "sm" | "md" | "lg";
  /**
   * Optional custom onPress handler. If provided, navigation logic is skipped.
   */
  onPress?: () => void;
};

export function BackButton({
  fallbackPath,
  variant = "secondary",
  size = "sm",
  onPress,
}: BackButtonProps) {
  const router = useRouter();

  const handlePress = () => {
    blurActiveElement();
    if (onPress) {
      onPress();
      return;
    }
    backOrHome(router, fallbackPath);
  };

  return (
    <IconButton
      accessibilityLabel="Go back"
      icon="chevron-back"
      size={size}
      variant={variant}
      onPress={handlePress}
    />
  );
}
