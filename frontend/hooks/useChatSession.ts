import { useEffect } from "react";

import { getSharedModelSelection } from "@/lib/chat-utils";
import { useChatStore } from "@/store/chat";

export function useChatSession(
  conversationId: string | undefined,
  activeAgentId: string | null,
) {
  const ensureSession = useChatStore((state) => state.ensureSession);
  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );
  const sessionSource = session?.source ?? null;
  const selectedModel = getSharedModelSelection(session?.metadata);

  useEffect(() => {
    if (activeAgentId && conversationId) {
      ensureSession(conversationId, activeAgentId);
    }
  }, [activeAgentId, conversationId, ensureSession]);

  return {
    session,
    sessionSource,
    selectedModel,
  };
}
