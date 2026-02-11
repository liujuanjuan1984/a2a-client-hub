import {
  ScrollView,
  type ScrollViewProps,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { useAppSafeArea } from "@/components/layout/useAppSafeArea";

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
  const insets = useAppSafeArea();

  return (
    <ScrollView
      className={className}
      style={[{ paddingTop: insets.top + topOffset }, style]}
      {...props}
    />
  );
}
