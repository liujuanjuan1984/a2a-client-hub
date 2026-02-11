import { type PropsWithChildren, useMemo } from "react";
import { type StyleProp, type ViewStyle, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getWebSafeAreaInset } from "@/components/layout/safeAreaWeb";

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
  const insets = useSafeAreaInsets();
  const safeTop = useMemo(
    () => Math.max(insets.top, getWebSafeAreaInset("top")),
    [insets.top],
  );

  return (
    <View
      className={className}
      style={[{ paddingTop: safeTop + topOffset }, style]}
    >
      {children}
    </View>
  );
}
