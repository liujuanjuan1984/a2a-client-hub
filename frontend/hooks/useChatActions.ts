import { useCallback } from "react";
import { useRouter } from "expo-router";
import { useChatStore } from "@/store/chat";
import { useValidateAgentMutation } from "@/hooks/useAgentsCatalogQuery";
import { toast } from "@/lib/toast";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { type SharedModelSelection } from "@/lib/chat-utils";

export function useChatActions(
  conversationId: string | undefined,
  activeAgentId: string | null,
  agent: any,
  session: any,
  scheduleStickToBottom: (animated: boolean) => void,
  clearInput: () => void,
) {
  const router = useRouter();
  const validateAgentMutation = useValidateAgentMutation();
  const sendMessage = useChatStore((state) => state.sendMessage);
  const retryMessage = useChatStore((state) => state.retryMessage);
  const resumeMessage = useChatStore((state) => state.resumeMessage);
  const ensureSession = useChatStore((state) => state.ensureSession);
  const setSharedModelSelection = useChatStore(
    (state) => state.setSharedModelSelection,
  );

  const handleSend = useCallback(
    (input: string, pendingInterrupt: any) => {
      if (!activeAgentId || !conversationId || !agent) {
        return;
      }
      if (pendingInterrupt) {
        toast.info(
          "Action required",
          "Please resolve the interactive action card before sending a new message.",
        );
        return;
      }
      if (!input.trim()) {
        return;
      }
      // These should be set via refs or just assume we want it
      // But the refs are in useChatScroll.
      // I will pass a callback or just let the caller handle ref updates.
      // Actually, I'll pass a function that wraps the ref updates.

      sendMessage(conversationId, activeAgentId, input, agent.source);
      clearInput();
      scheduleStickToBottom(true);
    },
    [
      activeAgentId,
      agent,
      conversationId,
      sendMessage,
      clearInput,
      scheduleStickToBottom,
    ],
  );

  const handleTest = useCallback(async () => {
    if (!activeAgentId || !agent) return;
    blurActiveElement();
    try {
      await validateAgentMutation.mutateAsync(activeAgentId);
      toast.success("Connection OK", `${agent.name} is online.`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Connection failed.";
      toast.error("Test failed", message);
    }
  }, [activeAgentId, agent, validateAgentMutation]);

  const handleRetry = useCallback(() => {
    if (
      !conversationId ||
      !activeAgentId ||
      session?.streamState === "streaming"
    )
      return;
    const runRetry = async () => {
      try {
        if (session?.streamState === "recoverable") {
          if (typeof resumeMessage === "function") {
            await resumeMessage(conversationId);
          }
          return;
        }
        if (typeof retryMessage === "function") {
          await retryMessage(
            conversationId,
            activeAgentId,
            agent?.source || "personal",
          );
        }
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Unable to retry message.";
        toast.error("Retry failed", message);
      }
    };
    runRetry();
  }, [
    activeAgentId,
    agent?.source,
    conversationId,
    retryMessage,
    resumeMessage,
    session?.streamState,
  ]);

  const handleSessionSelect = useCallback(
    (nextConversationId: string) => {
      if (!agent) {
        return;
      }
      blurActiveElement();
      router.replace(buildChatRoute(agent.id, nextConversationId));
    },
    [agent, router],
  );

  const handleModelSelect = useCallback(
    (selection: SharedModelSelection) => {
      if (!conversationId || !activeAgentId) {
        return;
      }
      ensureSession(conversationId, activeAgentId);
      setSharedModelSelection(conversationId, activeAgentId, selection);
      toast.success(
        "Model updated",
        `${selection.providerID} / ${selection.modelID}`,
      );
    },
    [activeAgentId, conversationId, ensureSession, setSharedModelSelection],
  );

  const clearModelSelection = useCallback(() => {
    if (!conversationId || !activeAgentId) {
      return;
    }
    ensureSession(conversationId, activeAgentId);
    setSharedModelSelection(conversationId, activeAgentId, null);
    toast.success("Model updated", "Using server default model.");
  }, [activeAgentId, conversationId, ensureSession, setSharedModelSelection]);

  return {
    handleSend,
    handleTest,
    testingConnection: validateAgentMutation.isPending,
    handleRetry,
    handleSessionSelect,
    handleModelSelect,
    clearModelSelection,
  };
}
