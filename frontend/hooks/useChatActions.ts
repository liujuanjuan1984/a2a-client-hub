import { useRouter } from "expo-router";
import { useCallback, useMemo } from "react";
import { type TextInput } from "react-native";

import { useValidateAgentMutation } from "@/hooks/useAgentsCatalogQuery";
import { useChatInput } from "@/hooks/useChatInput";
import { useChatShortcut } from "@/hooks/useChatShortcut";
import { type SharedModelSelection } from "@/lib/chat-utils";
import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { toast } from "@/lib/toast";
import { type AgentConfig } from "@/store/agents";
import { useChatStore } from "@/store/chat";

export function useChatActions({
  conversationId,
  agent,
  scheduleStickToBottom,
  onShortcutUsed,
}: {
  conversationId: string | undefined;
  agent: AgentConfig | undefined;
  scheduleStickToBottom: (animated: boolean) => void;
  onShortcutUsed?: () => void;
}) {
  const router = useRouter();
  const validateAgentMutation = useValidateAgentMutation();

  const activeAgentId = agent?.id ?? null;
  const sendMessage = useChatStore((state) => state.sendMessage);
  const retryMessage = useChatStore((state) => state.retryMessage);
  const resumeMessage = useChatStore((state) => state.resumeMessage);
  const ensureSession = useChatStore((state) => state.ensureSession);
  const setSharedModelSelection = useChatStore(
    (state) => state.setSharedModelSelection,
  );

  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );
  const pendingInterrupt = session?.pendingInterrupt ?? null;

  const handleSend = useCallback(
    (input: string) => {
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

      sendMessage(conversationId, activeAgentId, input, agent.source);
      inputHandlers.clearInput();
      scheduleStickToBottom(true);
    },
    [
      activeAgentId,
      agent,
      conversationId,
      sendMessage,
      scheduleStickToBottom,
      pendingInterrupt,
    ],
  );

  const inputHandlers = useChatInput(() => handleSend(inputHandlers.input));

  const shortcuts = useChatShortcut({
    setInput: inputHandlers.setInput,
    closeShortcutManager: onShortcutUsed || (() => {}),
    inputRef: inputHandlers.inputRef as React.RefObject<TextInput>,
  });

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

  const input = useMemo(
    () => ({
      ref: inputHandlers.inputRef,
      value: inputHandlers.input,
      height: inputHandlers.inputHeight,
      maxHeight: inputHandlers.maxInputHeight,
      onChange: inputHandlers.handleInputChange,
      onContentSizeChange: inputHandlers.handleContentSizeChange,
      onKeyPress: inputHandlers.handleKeyPress,
      onSend: () => handleSend(inputHandlers.input),
      clear: inputHandlers.clearInput,
      setInput: inputHandlers.setInput,
    }),
    [handleSend, inputHandlers],
  );

  return {
    input,
    shortcuts,
    testingConnection: validateAgentMutation.isPending,
    handlers: {
      onSend: handleSend,
      onTest: handleTest,
      onRetry: handleRetry,
      onSessionSelect: handleSessionSelect,
      onModelSelect: handleModelSelect,
      onModelClear: clearModelSelection,
    },
  };
}
