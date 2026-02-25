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
  variant = "neo",
  size = "md",
  loading,
  disabled,
  className,
  accessibilityLabel,
  ...props
}: IconButtonProps) {
  const variants: Record<IconButtonVariant, string> = {
    neo: "border-2 border-white bg-neo-yellow shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] active:translate-x-[1px] active:translate-y-[1px] active:shadow-none",
    primary:
      "border-2 border-white bg-neo-yellow shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] active:translate-x-[1px] active:translate-y-[1px] active:shadow-none",
    secondary:
      "border-2 border-white bg-surface shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] active:translate-x-[1px] active:translate-y-[1px] active:shadow-none",
    outline:
      "border-2 border-white bg-transparent shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] active:translate-x-[1px] active:translate-y-[1px] active:shadow-none",
    ghost: "",
    danger:
      "border-2 border-white bg-red-600 shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] active:translate-x-[1px] active:translate-y-[1px] active:shadow-none",
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
    neo: "#000000",
    primary: "#000000",
    secondary: "#FFFFFF",
    outline: "#FFFFFF",
    ghost: "#FFFFFF",
    danger: "#ffffff",
  };

  const isDisabled = disabled || loading;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      className={`items-center justify-center ${variants[variant]} ${sizes[size]} ${isDisabled ? "opacity-50" : ""} ${className || ""}`}
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
