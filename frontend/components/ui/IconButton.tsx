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
  | "secondary";
type IconButtonSize = "xs" | "sm" | "md" | "lg";

type IconButtonProps = Omit<PressableProps, "accessibilityLabel"> & {
  icon?: React.ComponentProps<typeof Ionicons>["name"];
  accessibilityLabel: string;
  variant?: IconButtonVariant;
  size?: IconButtonSize;
  loading?: boolean;
  iconColor?: string;
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
  ...props
}: IconButtonProps) {
  const variants: Record<IconButtonVariant, string> = {
    primary: "bg-primary",
    secondary: "bg-slate-800",
    outline: "border border-slate-700",
    ghost: "",
    danger: "border border-red-500/20 bg-red-500/10",
  };

  const sizes: Record<IconButtonSize, string> = {
    xs: "h-8 w-8",
    sm: "h-10 w-10",
    md: "h-11 w-11",
    lg: "h-12 w-12",
  };

  const iconSizes: Record<IconButtonSize, number> = {
    xs: 16,
    sm: 18,
    md: 20,
    lg: 22,
  };

  const iconColors: Record<IconButtonVariant, string> = {
    primary: "#ffffff",
    secondary: "#ffffff",
    outline: "#ffffff",
    ghost: "#ffffff",
    danger: "#f87171",
  };

  const isDisabled = disabled || loading;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      className={`items-center justify-center rounded-full ${variants[variant]} ${sizes[size]} ${isDisabled ? "opacity-50" : ""} ${className || ""}`}
      disabled={isDisabled}
      {...props}
    >
      {loading ? (
        <ActivityIndicator
          size="small"
          color={iconColor || iconColors[variant]}
        />
      ) : (
        icon && (
          <Ionicons
            name={icon}
            size={iconSizes[size]}
            color={iconColor || iconColors[variant]}
          />
        )
      )}
    </Pressable>
  );
}
