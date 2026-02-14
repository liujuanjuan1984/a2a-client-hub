import { useRouter } from "expo-router";
import { useCallback } from "react";

import { continueSession as continueSessionBinding } from "@/lib/api/sessions";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import {
  buildContinueBindingPayload,
  resolveCanonicalSessionId,
} from "@/lib/sessionBinding";
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
  const migrateSessionKey = useChatStore((state) => state.migrateSessionKey);

  const continueSession = useCallback(
    async ({ agentId, sessionId }: ContinueSessionInput) => {
      const unifiedSessionId = sessionId.trim();
      if (!unifiedSessionId) {
        toast.error("Continue session failed", "Missing session id.");
        return false;
      }

      try {
        const binding = await continueSessionBinding(unifiedSessionId);
        const canonicalSessionId = resolveCanonicalSessionId(
          unifiedSessionId,
          binding,
        );
        if (canonicalSessionId !== unifiedSessionId) {
          migrateSessionKey(unifiedSessionId, canonicalSessionId);
        }
        ensureSession(canonicalSessionId, agentId);
        bindExternalSession(
          canonicalSessionId,
          buildContinueBindingPayload(agentId, binding),
        );
        blurActiveElement();
        router.push(buildChatRoute(agentId, canonicalSessionId));
        return true;
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Continue failed.";
        toast.error("Continue session failed", message);
        return false;
      }
    },
    [bindExternalSession, ensureSession, migrateSessionKey, router],
  );

  return { continueSession };
};
