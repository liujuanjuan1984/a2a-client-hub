import { useCallback } from "react";

import { type SharedModelSelection } from "@/lib/chat-utils";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/store/chat";

export function useChatModelActions(
  conversationId: string | undefined,
  activeAgentId: string | null,
) {
  const ensureSession = useChatStore((state) => state.ensureSession);
  const setSharedModelSelection = useChatStore(
    (state) => state.setSharedModelSelection,
  );

  const handleModelSelect = useCallback(
    (selection: SharedModelSelection) => {
      if (!conversationId || !activeAgentId) return;
      ensureSession(conversationId, activeAgentId);
      setSharedModelSelection(conversationId, activeAgentId, selection);
      toast.success(
        "Model updated",
        `${selection.providerID} / ${selection.modelID}`,
      );
    },
    [activeAgentId, conversationId, ensureSession, setSharedModelSelection],
  );

  const handleModelClear = useCallback(() => {
    if (!conversationId || !activeAgentId) return;
    ensureSession(conversationId, activeAgentId);
    setSharedModelSelection(conversationId, activeAgentId, null);
    toast.success("Model updated", "Using server default model.");
  }, [activeAgentId, conversationId, ensureSession, setSharedModelSelection]);

  return { onModelSelect: handleModelSelect, onModelClear: handleModelClear };
}
