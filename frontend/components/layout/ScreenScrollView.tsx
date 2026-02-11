import { useMemo } from "react";
import {
  ScrollView,
  type ScrollViewProps,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getWebSafeAreaInset } from "@/components/layout/safeAreaWeb";

type ScreenScrollViewProps = Omit<ScrollViewProps, "style"> & {
  className?: string;
  style?: StyleProp<ViewStyle>;
  topOffset?: number;
};

export function ScreenScrollView({
  className = "flex-1 bg-background px-6",
  style,
  topOffset = 8,
  ...props
}: ScreenScrollViewProps) {
  const insets = useSafeAreaInsets();
  const safeTop = useMemo(
    () => Math.max(insets.top, getWebSafeAreaInset("top")),
    [insets.top],
  );

  return (
    <ScrollView
      className={className}
      style={[{ paddingTop: safeTop + topOffset }, style]}
      {...props}
    />
  );
}
