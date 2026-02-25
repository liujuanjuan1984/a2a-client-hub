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
  variant = "primary",
  size = "md",
  loading,
  iconLeft,
  iconRight,
  disabled,
  className,
  ...props
}: ButtonProps) {
  const variants = {
    neo: "bg-primary active:opacity-80",
    primary: "bg-primary active:opacity-80",
    secondary: "bg-gray-800 active:bg-gray-700",
    outline: "border border-white/20 active:bg-white/10",
    ghost: "active:bg-white/10",
    danger: "bg-red-500/20 active:bg-red-500/30",
  };

  const sizes = {
    xs: "px-3 py-1.5",
    sm: "px-4 py-2",
    md: "px-6 py-3",
    lg: "px-8 py-4",
  };

  const textSizes = {
    xs: "text-[11px]",
    sm: "text-[11px]",
    md: "text-sm",
    lg: "text-base",
  };

  const textColors = {
    neo: "text-black",
    primary: "text-black",
    secondary: "text-white",
    outline: "text-white/80",
    ghost: "text-white/80",
    danger: "text-red-400",
  };

  const iconColors = {
    neo: "#000000",
    primary: "#000000",
    secondary: "#FFFFFF",
    outline: "#FFFFFF",
    ghost: "#FFFFFF",
    danger: "#f87171",
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
      className={`flex-row items-center justify-center rounded-xl ${variants[variant]} ${sizes[size]} ${isDisabled ? "opacity-40" : ""} ${className || ""}`}
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
      <Text className={`font-bold ${textColors[variant]} ${textSizes[size]}`}>
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
          color={iconColors[variant]}
          style={{ marginLeft: 8 }}
        />
      )}
    </Pressable>
  );
}
