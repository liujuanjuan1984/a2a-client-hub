import { Ionicons } from "@expo/vector-icons";
import {
  ActivityIndicator,
  Pressable,
  type PressableProps,
} from "react-native";

import {
  type ButtonSize,
  type ButtonVariant,
  buttonIconColors,
  buttonVariants,
} from "./buttonStyles";

type IconButtonProps = Omit<PressableProps, "accessibilityLabel"> & {
  icon: React.ComponentProps<typeof Ionicons>["name"];
  accessibilityLabel: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
};

export function IconButton({
  icon,
  variant = "primary",
  size = "md",
  loading,
  disabled,
  className,
  accessibilityLabel,
  ...props
}: IconButtonProps) {
  const sizes: Record<ButtonSize, string> = {
    xs: "h-8 w-8",
    sm: "h-10 w-10",
    md: "h-11 w-11",
    lg: "h-12 w-12",
  };

  const iconSizes: Record<ButtonSize, number> = {
    xs: 14,
    sm: 18,
    md: 20,
    lg: 22,
  };

  const isDisabled = disabled || loading;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      className={`items-center justify-center rounded-xl ${buttonVariants[variant]} ${sizes[size]} ${isDisabled ? "opacity-40" : ""} ${className || ""}`}
      disabled={isDisabled}
      {...props}
    >
      {loading ? (
        <ActivityIndicator size="small" color={buttonIconColors[variant]} />
      ) : (
        <Ionicons
          name={icon}
          size={iconSizes[size]}
          color={buttonIconColors[variant]}
        />
      )}
    </Pressable>
  );
}
