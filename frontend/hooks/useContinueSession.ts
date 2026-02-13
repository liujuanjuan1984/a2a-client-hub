import { useRouter } from "expo-router";
import { useCallback } from "react";

import { continueSession as continueSessionBinding } from "@/lib/api/sessions";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/store/chat";

type ContinueSessionInput = {
  agentId: string;
  sessionId: string;
};

export const useContinueSession = () => {
  const router = useRouter();
  const ensureSession = useChatStore((state) => state.ensureSession);
  const bindOpencodeSession = useChatStore(
    (state) => state.bindOpencodeSession,
  );

  const continueSession = useCallback(
    async ({ agentId, sessionId }: ContinueSessionInput) => {
      const unifiedSessionId = sessionId.trim();
      if (!unifiedSessionId) {
        toast.error("Continue session failed", "Missing session id.");
        return false;
      }

      try {
        const binding = await continueSessionBinding(unifiedSessionId);
        ensureSession(unifiedSessionId, agentId);
        const opencodeSessionId =
          typeof binding.metadata.opencode_session_id === "string"
            ? binding.metadata.opencode_session_id
            : undefined;
        bindOpencodeSession(unifiedSessionId, {
          agentId,
          opencodeSessionId,
          contextId: binding.contextId ?? undefined,
          metadata: binding.metadata,
        });
        blurActiveElement();
        router.push(buildChatRoute(agentId, unifiedSessionId));
        return true;
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Continue failed.";
        toast.error("Continue session failed", message);
        return false;
      }
    },
    [bindOpencodeSession, ensureSession, router],
  );

  return { continueSession };
};
