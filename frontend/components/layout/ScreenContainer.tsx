import { type PropsWithChildren } from "react";
import { type StyleProp, type ViewStyle, View } from "react-native";

import { useAppSafeArea } from "@/components/layout/useAppSafeArea";

type ScreenContainerProps = PropsWithChildren<{
  className?: string;
  style?: StyleProp<ViewStyle>;
  topOffset?: number;
}>;

export function ScreenContainer({
  children,
  className = "flex-1 bg-background px-6",
  style,
  topOffset = 8,
}: ScreenContainerProps) {
  const insets = useAppSafeArea();

  return (
    <View
      className={className}
      style={[{ paddingTop: insets.top + topOffset }, style]}
    >
      {children}
    </View>
  );
}
