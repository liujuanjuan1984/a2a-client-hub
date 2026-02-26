import { type PropsWithChildren } from "react";
import { type StyleProp, type ViewStyle, View } from "react-native";

import { PAGE_TOP_OFFSET } from "@/components/layout/spacing";
import { useAppSafeArea } from "@/components/layout/useAppSafeArea";

type ScreenContainerProps = PropsWithChildren<{
  className?: string;
  style?: StyleProp<ViewStyle>;
  topOffset?: number;
}>;

export function ScreenContainer({
  children,
  className = "flex-1 bg-background px-3 sm:px-6",
  style,
  topOffset = PAGE_TOP_OFFSET,
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
