import { Platform } from "react-native";

type SafeAreaEdge = "top" | "right" | "bottom" | "left";

type WebSafeAreaInsets = Record<SafeAreaEdge, number>;

const EDGE_CSS_VAR: Record<SafeAreaEdge, string> = {
  top: "--safe-area-inset-top",
  right: "--safe-area-inset-right",
  bottom: "--safe-area-inset-bottom",
  left: "--safe-area-inset-left",
};

const ZERO_INSETS: WebSafeAreaInsets = {
  top: 0,
  right: 0,
  bottom: 0,
  left: 0,
};

const parseInsetValue = (value: string) => {
  const parsed = Number.parseFloat(value.trim());
  return Number.isFinite(parsed) ? parsed : 0;
};

export function getWebSafeAreaInsets(): WebSafeAreaInsets {
  if (Platform.OS !== "web") return ZERO_INSETS;
  if (typeof window === "undefined" || typeof document === "undefined") {
    return ZERO_INSETS;
  }

  const computed = window.getComputedStyle(document.documentElement);
  return {
    top: parseInsetValue(computed.getPropertyValue(EDGE_CSS_VAR.top)),
    right: parseInsetValue(computed.getPropertyValue(EDGE_CSS_VAR.right)),
    bottom: parseInsetValue(computed.getPropertyValue(EDGE_CSS_VAR.bottom)),
    left: parseInsetValue(computed.getPropertyValue(EDGE_CSS_VAR.left)),
  };
}
