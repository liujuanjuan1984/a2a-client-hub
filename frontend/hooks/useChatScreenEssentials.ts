import { useCallback, useState } from "react";

import { PAGE_TOP_OFFSET } from "@/components/layout/spacing";
import { useAppSafeArea } from "@/components/layout/useAppSafeArea";

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
