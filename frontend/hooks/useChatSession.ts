import { useRouter } from "expo-router";
import { useEffect, useRef } from "react";

import { type ChatMessage } from "@/lib/api/chat-utils";
import { continueSession } from "@/lib/api/sessions";
import { buildChatRoute } from "@/lib/routes";
import { buildContinueBindingPayload } from "@/lib/sessionBinding";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/store/chat";

export function useChatSession(
  conversationId: string | undefined,
  activeAgentId: string | null,
  messages: ChatMessage[],
) {
  const router = useRouter();
  const ensureSession = useChatStore((state) => state.ensureSession);
  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );
  const sessionSource = session?.source ?? null;
  const mountedAtRef = useRef(Date.now());

  useEffect(() => {
    if (activeAgentId && conversationId) {
      ensureSession(conversationId, activeAgentId);
    }
  }, [activeAgentId, conversationId, ensureSession]);

  useEffect(() => {
    if (!conversationId || !activeAgentId) return;
    const boundAgentId = activeAgentId;
    const normalizedConversationId = conversationId;
    const hasHistory = messages.length > 0;
    if (sessionSource === "manual" && !hasHistory) {
      return;
    }

    let cancelled = false;
    continueSession(conversationId)
      .then((binding) => {
        if (cancelled) return;
        const resolvedConversationId = binding.conversationId.trim();
        if (resolvedConversationId !== normalizedConversationId) {
          router.replace(buildChatRoute(boundAgentId, resolvedConversationId));
          return;
        }
        const current = useChatStore.getState().sessions[conversationId];
        const hasLocalBinding =
          (typeof current?.contextId === "string" &&
            current.contextId.trim()) ||
          (typeof current?.externalSessionRef?.externalSessionId === "string" &&
            current.externalSessionRef.externalSessionId.trim()) ||
          Object.keys(current?.metadata ?? {}).length > 0;
        const hasBindingMetadata =
          (typeof binding.metadata?.contextId === "string" &&
            binding.metadata.contextId.trim()) ||
          (typeof binding.metadata?.externalSessionId === "string" &&
            binding.metadata.externalSessionId.trim()) ||
          (typeof binding.metadata?.provider === "string" &&
            binding.metadata.provider.trim());
        if (hasLocalBinding && !hasBindingMetadata) {
          return;
        }
        ensureSession(conversationId, boundAgentId);
        useChatStore
          .getState()
          .bindExternalSession(
            conversationId,
            buildContinueBindingPayload(boundAgentId, binding),
          );
      })
      .catch((error) => {
        if (cancelled) return;
        if (
          sessionSource === "manual" &&
          error instanceof Error &&
          error.message === "session_not_found"
        ) {
          return;
        }
        const message = error instanceof Error ? error.message : "Bind failed.";
        toast.error("Continue session failed", message);
      });

    return () => {
      cancelled = true;
    };
  }, [
    activeAgentId,
    ensureSession,
    messages.length,
    conversationId,
    router,
    sessionSource,
  ]);

  return { session, sessionSource, mountedAtRef };
}
