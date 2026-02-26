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
  const variants: Record<IconButtonVariant, string> = {
    neo: "bg-yellow-500/90 active:bg-yellow-500",
    primary: "bg-yellow-500/90 active:bg-yellow-500",
    secondary: "bg-slate-800/60 border border-white/5 active:bg-slate-800",
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
    neo: "#000000",
    primary: "#000000",
    secondary: "#94a3b8",
    outline: "#64748b",
    ghost: "#64748b",
    danger: "#f87171",
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
        <ActivityIndicator size="small" color={iconColors[variant]} />
      ) : (
        <Ionicons
          name={icon}
          size={iconSizes[size]}
          color={iconColors[variant]}
        />
      )}
    </Pressable>
  );
}
