import { Platform } from "react-native";

type SafeAreaEdge = "top" | "right" | "bottom" | "left";

const EDGE_CSS_VAR: Record<SafeAreaEdge, string> = {
  top: "--safe-area-inset-top",
  right: "--safe-area-inset-right",
  bottom: "--safe-area-inset-bottom",
  left: "--safe-area-inset-left",
};

export function getWebSafeAreaInset(edge: SafeAreaEdge): number {
  if (Platform.OS !== "web") return 0;
  if (typeof window === "undefined" || typeof document === "undefined") {
    return 0;
  }

  const variable = EDGE_CSS_VAR[edge];
  const rawValue = window
    .getComputedStyle(document.documentElement)
    .getPropertyValue(variable)
    .trim();
  const parsed = Number.parseFloat(rawValue);

  return Number.isFinite(parsed) ? parsed : 0;
}
