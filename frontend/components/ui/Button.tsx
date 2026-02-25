import { Ionicons } from "@expo/vector-icons";
import {
  ActivityIndicator,
  Pressable,
  type PressableProps,
  Text,
} from "react-native";

interface ButtonProps extends PressableProps {
  label: string;
  variant?: "primary" | "outline" | "ghost" | "danger" | "secondary" | "neo";
  size?: "xs" | "sm" | "md" | "lg";
  loading?: boolean;
  iconLeft?: React.ComponentProps<typeof Ionicons>["name"];
  iconRight?: React.ComponentProps<typeof Ionicons>["name"];
}

export function Button({
  label,
  variant = "neo",
  size = "md",
  loading,
  iconLeft,
  iconRight,
  disabled,
  className,
  ...props
}: ButtonProps) {
  const variants = {
    neo: "border-neo border-black bg-neo-yellow shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
    primary:
      "border-neo border-black bg-neo-yellow shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
    secondary:
      "border-neo border-black bg-white shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
    outline:
      "border-neo border-black bg-white shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
    ghost: "",
    danger:
      "border-neo border-black bg-red-500 shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
  };

  const sizes = {
    xs: "px-3 py-1.5",
    sm: "px-4 py-2",
    md: "px-6 py-3",
    lg: "px-8 py-4",
  };

  const textSizes = {
    xs: "text-[10px]",
    sm: "text-xs",
    md: "text-sm",
    lg: "text-base",
  };

  const textColors = {
    neo: "text-neo-text",
    primary: "text-neo-text",
    secondary: "text-neo-text",
    outline: "text-neo-text",
    ghost: "text-neo-text",
    danger: "text-white",
  };

  const iconColors = {
    neo: "#000000",
    primary: "#000000",
    secondary: "#000000",
    outline: "#000000",
    ghost: "#000000",
    danger: "#ffffff",
  };

  const iconSizes = {
    xs: 14,
    sm: 16,
    md: 18,
    lg: 20,
  };

  const isDisabled = disabled || loading;

  return (
    <Pressable
      className={`flex-row items-center justify-center ${variants[variant]} ${sizes[size]} ${isDisabled ? "opacity-50" : ""} ${className || ""}`}
      disabled={isDisabled}
      {...props}
    >
      {iconLeft ? (
        <Ionicons
          name={iconLeft}
          size={iconSizes[size]}
          color={iconColors[variant]}
          style={{ marginRight: 8 }}
        />
      ) : null}
      <Text
        className={`font-semibold ${textColors[variant]} ${textSizes[size]}`}
      >
        {label}
      </Text>
      {!loading && iconRight ? (
        <Ionicons
          name={iconRight}
          size={iconSizes[size]}
          color={iconColors[variant]}
          style={{ marginLeft: 6 }}
        />
      ) : null}
      {loading && (
        <ActivityIndicator
          size="small"
          color={variant === "danger" ? "#f87171" : "#ffffff"}
          style={{ marginLeft: 8 }}
        />
      )}
    </Pressable>
  );
}
