import { useRouter } from "expo-router";
import { useEffect } from "react";

import { type AgentConfig } from "@/store/agents";

export function useChatNavigation({
  hasFetchedAgents,
  agent,
}: {
  hasFetchedAgents: boolean;
  agent: AgentConfig | undefined;
}) {
  const router = useRouter();

  useEffect(() => {
    if (hasFetchedAgents && !agent) {
      router.replace("/");
    }
  }, [agent, hasFetchedAgents, router]);
}
