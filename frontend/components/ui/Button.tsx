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
    neo: "border-neo border-white bg-neo-yellow shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
    primary:
      "border-neo border-white bg-neo-yellow shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
    secondary:
      "border-neo border-white bg-surface shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
    outline:
      "border-neo border-white bg-transparent shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
    ghost: "",
    danger:
      "border-neo border-white bg-red-600 shadow-neo active:translate-x-[2px] active:translate-y-[2px] active:shadow-none",
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
    neo: "text-black",
    primary: "text-black",
    secondary: "text-white",
    outline: "text-white",
    ghost: "text-white",
    danger: "text-white",
  };

  const iconColors = {
    neo: "#000000",
    primary: "#000000",
    secondary: "#FFFFFF",
    outline: "#FFFFFF",
    ghost: "#FFFFFF",
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
