import { useMemo } from "react";
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getWebSafeAreaInsets } from "@/components/layout/safeAreaWeb";

type UseAppSafeAreaOptions = {
  maxBottomInset?: number;
};

export function useAppSafeArea(options?: UseAppSafeAreaOptions) {
  const insets = useSafeAreaInsets();
  const maxBottomInset = options?.maxBottomInset;

  return useMemo(() => {
    if (Platform.OS !== "web") {
      const bottom =
        typeof maxBottomInset === "number"
          ? Math.min(insets.bottom, maxBottomInset)
          : insets.bottom;
      return { ...insets, bottom };
    }

    const webInsets = getWebSafeAreaInsets();
    const top = Math.max(insets.top, webInsets.top);
    const right = Math.max(insets.right, webInsets.right);
    const left = Math.max(insets.left, webInsets.left);
    const rawBottom = Math.max(insets.bottom, webInsets.bottom);
    const bottom =
      typeof maxBottomInset === "number"
        ? Math.min(rawBottom, maxBottomInset)
        : rawBottom;

    return { top, right, bottom, left };
  }, [insets.bottom, insets.left, insets.right, insets.top, maxBottomInset]);
}
