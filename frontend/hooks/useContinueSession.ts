import { useRouter } from "expo-router";
import { useCallback } from "react";

import { continueSession as continueSessionBinding } from "@/lib/api/sessions";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { buildContinueBindingPayload } from "@/lib/sessionBinding";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/store/chat";

type ContinueSessionInput = {
  agentId: string;
  conversationId: string;
  createdAt?: string | null;
  lastActiveAt?: string | null;
};

export const useContinueSession = () => {
  const router = useRouter();
  const ensureSession = useChatStore((state) => state.ensureSession);
  const bindExternalSession = useChatStore(
    (state) => state.bindExternalSession,
  );

  const continueSession = useCallback(
    async ({
      agentId,
      conversationId,
      createdAt,
      lastActiveAt,
    }: ContinueSessionInput) => {
      const normalizedConversationId = conversationId.trim();
      if (!normalizedConversationId) {
        toast.error("Continue session failed", "Missing conversation id.");
        return false;
      }

      try {
        const binding = await continueSessionBinding(normalizedConversationId);
        const resolvedConversationId = binding.conversationId.trim();
        ensureSession(resolvedConversationId, agentId, {
          createdAt,
          lastActiveAt,
        });
        bindExternalSession(
          resolvedConversationId,
          buildContinueBindingPayload(agentId, binding),
        );
        blurActiveElement();
        router.push(buildChatRoute(agentId, resolvedConversationId));
        return true;
      } catch (error) {
        const errorCode =
          error && typeof error === "object" && "errorCode" in error
            ? (error as { errorCode?: unknown }).errorCode
            : null;
        const message =
          (typeof errorCode === "string" &&
            errorCode === "session_forbidden") ||
          (error instanceof Error &&
            error.message.trim() === "session_forbidden")
            ? "You do not have permission to continue this session."
            : error instanceof Error
              ? error.message
              : "Continue failed.";
        toast.error("Continue session failed", message);
        return false;
      }
    },
    [bindExternalSession, ensureSession, router],
  );

  return { continueSession };
};
