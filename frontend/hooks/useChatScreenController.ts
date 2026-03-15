import { useA2AIntegration } from "./useA2AIntegration";
import { useAgentSelection } from "./useAgentSelection";
import { useChatNavigation } from "./useChatNavigation";
import { useChatSession } from "./useChatSession";
import { useChatTimeline } from "./useChatTimeline";
import { useChatUIOrchestrator } from "./useChatUIOrchestrator";
import { useSessionBinding } from "./useSessionBinding";

export function useChatScreenController({
  routeAgentId,
  conversationId,
}: {
  routeAgentId?: string | null;
  conversationId?: string;
}) {
  const { activeAgentId, agent, hasFetchedAgents } =
    useAgentSelection(routeAgentId);

  const { session, sessionSource, selectedModel } = useChatSession(
    conversationId,
    activeAgentId,
  );

  const { history, scroll } = useChatTimeline({
    conversationId,
    streamState: session?.streamState,
  });

  useSessionBinding({
    conversationId,
    activeAgentId,
    sessionSource,
    messages: history.messages,
  });

  useChatNavigation({ hasFetchedAgents, agent });

  const interaction = useChatUIOrchestrator({
    conversationId,
    agent,
    scheduleStickToBottom: scroll.scheduleStickToBottom,
    selectedModel,
  });

  const a2a = useA2AIntegration({
    conversationId,
    agent,
  });

  return {
    navigation: {
      agent,
      activeAgentId,
      hasFetchedAgents,
      conversationId,
      session,
      sessionSource,
    },
    ui: interaction.ui,
    history,
    input: interaction.input,
    scroll: scroll.props,
    a2a,
    modals: interaction.modals,
    actions: interaction.actions,
  };
}
