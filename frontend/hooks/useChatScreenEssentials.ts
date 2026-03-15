import { useCallback, useState } from "react";
import { useAppSafeArea } from "@/components/layout/useAppSafeArea";
import { PAGE_TOP_OFFSET } from "@/components/layout/spacing";

export function useChatScreenEssentials() {
  const insets = useAppSafeArea();
  const [showDetails, setShowDetails] = useState(false);

  const toggleDetails = useCallback(() => {
    setShowDetails((current) => !current);
  }, []);

  return {
    showDetails,
    toggleDetails,
    topInset: insets.top + PAGE_TOP_OFFSET,
  };
}
