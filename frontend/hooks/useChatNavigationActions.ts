import { useRouter } from "expo-router";
import { useCallback } from "react";

import { blurActiveElement } from "@/lib/focus";
import { buildChatRoute } from "@/lib/routes";
import { type AgentConfig } from "@/store/agents";

export function useChatNavigationActions(agent: AgentConfig | undefined) {
  const router = useRouter();

  const handleSessionSelect = useCallback(
    (nextConversationId: string) => {
      if (!agent) return;
      blurActiveElement();
      router.replace(buildChatRoute(agent.id, nextConversationId));
    },
    [agent, router],
  );

  return { onSessionSelect: handleSessionSelect };
}
