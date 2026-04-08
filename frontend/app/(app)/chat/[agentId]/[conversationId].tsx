import { useLocalSearchParams } from "expo-router";
import { lazy, Suspense, useMemo } from "react";

import { buildGeneratingTitle, PageTitle } from "@/components/layout/PageTitle";
import { FullscreenLoader } from "@/components/ui/FullscreenLoader";
import { useAgentsCatalogQuery } from "@/hooks/useAgentsCatalogQuery";
import { useChatStore } from "@/store/chat";

const LazyChatScreen = lazy(async () => {
  const module = await import("@/screens/ChatScreen");
  return { default: module.ChatScreen };
});

export default function ChatSession() {
  const { agentId, conversationId } = useLocalSearchParams<{
    agentId: string;
    conversationId: string;
  }>();
  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );
  const { data: agents = [] } = useAgentsCatalogQuery(true);

  const isGenerating = session?.streamState === "streaming";

  const agentName = useMemo(() => {
    const matchedAgent = agents.find((item) => item.id === agentId);
    return matchedAgent?.name?.trim() || agentId;
  }, [agents, agentId]);

  const title = useMemo(() => {
    const baseTitle = agentName;
    return buildGeneratingTitle({
      baseTitle,
      isGenerating,
    });
  }, [agentName, isGenerating]);

  return (
    <>
      <PageTitle title={title} />
      <Suspense fallback={<FullscreenLoader message="Loading chat..." />}>
        <LazyChatScreen agentId={agentId} conversationId={conversationId} />
      </Suspense>
    </>
  );
}
