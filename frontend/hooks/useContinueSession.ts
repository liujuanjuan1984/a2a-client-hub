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
  const bindExternalSession = useChatStore(
    (state) => state.bindExternalSession,
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
        bindExternalSession(unifiedSessionId, {
          agentId,
          conversationId: binding.conversationId ?? undefined,
          provider: binding.provider ?? undefined,
          externalSessionId: binding.externalSessionId ?? undefined,
          contextId: binding.contextId ?? undefined,
          bindingMetadata: binding.bindingMetadata ?? undefined,
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
    [bindExternalSession, ensureSession, router],
  );

  return { continueSession };
};
