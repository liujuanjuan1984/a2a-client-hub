import { useChatConnectionActions } from "./useChatConnectionActions";
import { useChatMessageActions } from "./useChatMessageActions";
import { useChatModelActions } from "./useChatModelActions";
import { useChatNavigationActions } from "./useChatNavigationActions";

import { type AgentConfig } from "@/store/agents";

export function useChatActions({
  conversationId,
  agent,
  scheduleStickToBottom,
}: {
  conversationId: string | undefined;
  agent: AgentConfig | undefined;
  scheduleStickToBottom: (animated: boolean) => void;
}) {
  const activeAgentId = agent?.id ?? null;

  const { input, onSend, onRetry } = useChatMessageActions({
    conversationId,
    agent,
    scheduleStickToBottom,
  });

  const { onSessionSelect } = useChatNavigationActions(agent);

  const { onModelSelect, onModelClear } = useChatModelActions(
    conversationId,
    activeAgentId,
  );

  const { onTest, testingConnection } = useChatConnectionActions(agent);

  return {
    input,
    testingConnection,
    handlers: {
      onSend,
      onTest,
      onRetry,
      onSessionSelect,
      onModelSelect,
      onModelClear,
    },
  };
}
