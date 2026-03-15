import { useAgentSelection } from "./useAgentSelection";
import { useChatNavigation } from "./useChatNavigation";
import { useChatSession } from "./useChatSession";

export function useChatNavigationState({
  routeAgentId,
  conversationId,
  messages,
}: {
  routeAgentId?: string | null;
  conversationId?: string;
  messages: any[]; // ChatMessage[] but using any for simplicity if types are complex to import here
}) {
  const { activeAgentId, agent, hasFetchedAgents } =
    useAgentSelection(routeAgentId);

  useChatNavigation({ hasFetchedAgents, agent });

  const { session, sessionSource, mountedAtRef } = useChatSession(
    conversationId,
    activeAgentId,
    messages,
  );

  return {
    agent,
    activeAgentId,
    hasFetchedAgents,
    session,
    sessionSource,
    mountedAtRef,
  };
}
