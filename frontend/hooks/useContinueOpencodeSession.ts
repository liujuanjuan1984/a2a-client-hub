import { useRouter } from "expo-router";
import { useCallback } from "react";

import {
  continueOpencodeSession,
  type AgentSource,
} from "@/lib/api/opencodeSessions";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/store/chat";

type ContinueOpencodeSessionInput = {
  agentId: string;
  sessionId: string;
  source?: AgentSource;
};

export const useContinueOpencodeSession = () => {
  const router = useRouter();
  const generateSessionId = useChatStore((state) => state.generateSessionId);
  const ensureSession = useChatStore((state) => state.ensureSession);
  const bindOpencodeSession = useChatStore(
    (state) => state.bindOpencodeSession,
  );

  const continueSession = useCallback(
    async ({
      agentId,
      sessionId,
      source = "personal",
    }: ContinueOpencodeSessionInput) => {
      const opencodeSessionId = sessionId.trim();
      if (!opencodeSessionId) {
        toast.error("Continue session failed", "Missing session id.");
        return false;
      }

      try {
        const binding = await continueOpencodeSession(
          agentId,
          opencodeSessionId,
          {
            source,
          },
        );
        const chatSessionId = generateSessionId();
        ensureSession(chatSessionId, agentId);
        bindOpencodeSession(chatSessionId, {
          agentId,
          opencodeSessionId,
          contextId: binding.contextId ?? undefined,
          metadata: binding.metadata,
        });
        blurActiveElement();
        router.push(
          buildChatRoute(agentId, chatSessionId, {
            opencodeSessionId,
          }),
        );
        return true;
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Continue failed.";
        toast.error("Continue session failed", message);
        return false;
      }
    },
    [bindOpencodeSession, ensureSession, generateSessionId, router],
  );

  return { continueSession };
};
