import { useCallback, useMemo } from "react";

import { useChatInput } from "@/hooks/useChatInput";
import { toast } from "@/lib/toast";
import { type AgentConfig } from "@/store/agents";
import { useChatStore } from "@/store/chat";

export function useChatMessageActions({
  conversationId,
  agent,
  scheduleStickToBottom,
}: {
  conversationId: string | undefined;
  agent: AgentConfig | undefined;
  scheduleStickToBottom: (animated: boolean) => void;
}) {
  const activeAgentId = agent?.id ?? null;
  const sendMessage = useChatStore((state) => state.sendMessage);
  const retryMessage = useChatStore((state) => state.retryMessage);
  const resumeMessage = useChatStore((state) => state.resumeMessage);

  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );
  const pendingInterrupt = session?.pendingInterrupt ?? null;

  const handleSend = useCallback(
    (input: string) => {
      if (!activeAgentId || !conversationId || !agent) return;
      if (pendingInterrupt) {
        toast.info(
          "Action required",
          "Please resolve the interactive action card before sending a new message.",
        );
        return;
      }
      if (!input.trim()) return;

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
          if (typeof resumeMessage === "function")
            await resumeMessage(conversationId);
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

  return { input, onSend: handleSend, onRetry: handleRetry };
}
