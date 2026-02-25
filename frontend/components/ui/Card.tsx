import React from "react";
import { View, type ViewProps } from "react-native";

interface CardProps extends ViewProps {
  children: React.ReactNode;
}

export function Card({ children, className, ...props }: CardProps) {
  return (
    <View
      className={`bg-surface border-neo border-white shadow-neo ${className || ""}`}
      {...props}
    >
      {children}
    </View>
  );
}
