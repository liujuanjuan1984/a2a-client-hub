import { useLocalSearchParams } from "expo-router";
import { useMemo } from "react";

import { buildGeneratingTitle, PageTitle } from "@/components/layout/PageTitle";
import { ChatScreen } from "@/screens/ChatScreen";
import { useChatStore } from "@/store/chat";

export default function ChatSession() {
  const { agentId, conversationId } = useLocalSearchParams<{
    agentId: string;
    conversationId: string;
  }>();
  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );

  const isGenerating =
    session?.streamState === "streaming" ||
    session?.streamState === "rebinding";

  const title = useMemo(() => {
    const baseTitle = `Chat with ${agentId}`;
    return buildGeneratingTitle({
      baseTitle,
      isGenerating,
    });
  }, [agentId, isGenerating]);

  return (
    <>
      <PageTitle title={title} />
      <ChatScreen agentId={agentId} conversationId={conversationId} />
    </>
  );
}
