import { Ionicons } from "@expo/vector-icons";
import {
  ActivityIndicator,
  Pressable,
  type PressableProps,
  Text,
} from "react-native";

import {
  type ButtonSize,
  type ButtonVariant,
  buttonIconColors,
  buttonVariants,
} from "./buttonStyles";

interface ButtonProps extends PressableProps {
  label: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
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
    neo: "text-black/80",
    primary: "text-black/80",
    secondary: "text-slate-300",
    outline: "text-slate-400",
    ghost: "text-slate-500",
    danger: "text-red-400/80",
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
      className={`flex-row items-center justify-center rounded-xl ${buttonVariants[variant]} ${sizes[size]} ${isDisabled ? "opacity-40" : ""} ${className || ""}`}
      disabled={isDisabled}
      {...props}
    >
      {iconLeft ? (
        <Ionicons
          name={iconLeft}
          size={iconSizes[size]}
          color={buttonIconColors[variant]}
          style={{ marginRight: 8 }}
        />
      ) : null}
      <Text
        className={`${size === "xs" ? "font-medium" : "font-bold"} ${textColors[variant]} ${textSizes[size]}`}
      >
        {label}
      </Text>
      {!loading && iconRight ? (
        <Ionicons
          name={iconRight}
          size={iconSizes[size]}
          color={buttonIconColors[variant]}
          style={{ marginLeft: 6 }}
        />
      ) : null}
      {loading && (
        <ActivityIndicator
          size="small"
          color={buttonIconColors[variant]}
          style={{ marginLeft: 8 }}
        />
      )}
    </Pressable>
  );
}
