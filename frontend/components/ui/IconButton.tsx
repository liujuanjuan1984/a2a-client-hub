import { Ionicons } from "@expo/vector-icons";
import {
  ActivityIndicator,
  Pressable,
  type PressableProps,
} from "react-native";

type IconButtonVariant =
  | "primary"
  | "outline"
  | "ghost"
  | "danger"
  | "secondary"
  | "neo";
type IconButtonSize = "xs" | "sm" | "md" | "lg";

type IconButtonProps = Omit<PressableProps, "accessibilityLabel"> & {
  icon: React.ComponentProps<typeof Ionicons>["name"];
  accessibilityLabel: string;
  variant?: IconButtonVariant;
  size?: IconButtonSize;
  loading?: boolean;
  iconColor?: string;
  iconSize?: number;
};

export function IconButton({
  icon,
  variant = "primary",
  size = "md",
  loading,
  disabled,
  className,
  accessibilityLabel,
  iconColor,
  iconSize,
  ...props
}: IconButtonProps) {
  const variants: Record<IconButtonVariant, string> = {
    neo: "bg-yellow-400/85 active:bg-yellow-300/90",
    primary: "bg-yellow-400/85 active:bg-yellow-300/90",
    secondary: "bg-slate-700/55 active:bg-slate-600/65",
    outline: "border border-white/10 active:bg-white/5",
    ghost: "active:bg-white/5",
    danger: "bg-red-500/10 border border-red-500/20 active:bg-red-500/20",
  };

  const sizes: Record<IconButtonSize, string> = {
    xs: "h-8 w-8",
    sm: "h-10 w-10",
    md: "h-11 w-11",
    lg: "h-12 w-12",
  };

  const iconSizes: Record<IconButtonSize, number> = {
    xs: 14,
    sm: 18,
    md: 20,
    lg: 22,
  };

  const iconColors: Record<IconButtonVariant, string> = {
    neo: "#000000cc",
    primary: "#000000cc",
    secondary: "#e2e8f0",
    outline: "#64748b",
    ghost: "#475569",
    danger: "#f87171cc",
  };

  const isDisabled = disabled || loading;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      className={`items-center justify-center rounded-xl ${variants[variant]} ${sizes[size]} ${isDisabled ? "opacity-40" : ""} ${className || ""}`}
      disabled={isDisabled}
      {...props}
    >
      {loading ? (
        <ActivityIndicator
          size="small"
          color={iconColor || iconColors[variant]}
        />
      ) : (
        <Ionicons
          name={icon}
          size={iconSize || iconSizes[size]}
          color={iconColor || iconColors[variant]}
        />
      )}
    </Pressable>
  );
}
