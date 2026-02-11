import { useEffect, useMemo, useState } from "react";
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getWebSafeAreaInsets } from "@/components/layout/safeAreaWeb";

type UseAppSafeAreaOptions = {
  maxBottomInset?: number;
};

export function useAppSafeArea(options?: UseAppSafeAreaOptions) {
  const insets = useSafeAreaInsets();
  const maxBottomInset = options?.maxBottomInset;
  const [viewportVersion, setViewportVersion] = useState(0);

  useEffect(() => {
    if (Platform.OS !== "web") return;
    if (typeof window === "undefined") return;

    const bump = () => setViewportVersion((value) => value + 1);

    // Trigger one post-layout recompute; some iOS PWA entries report 0 inset
    // during first paint.
    const rafId = window.requestAnimationFrame(bump);
    window.addEventListener("resize", bump);
    window.addEventListener("orientationchange", bump);
    window.visualViewport?.addEventListener("resize", bump);

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("resize", bump);
      window.removeEventListener("orientationchange", bump);
      window.visualViewport?.removeEventListener("resize", bump);
    };
  }, []);

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
  }, [
    insets.bottom,
    insets.left,
    insets.right,
    insets.top,
    maxBottomInset,
    viewportVersion,
  ]);
}
