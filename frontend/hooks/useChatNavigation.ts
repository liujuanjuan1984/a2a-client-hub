import { useEffect } from "react";
import { useRouter } from "expo-router";

export function useChatNavigation({
  hasFetchedAgents,
  agent,
}: {
  hasFetchedAgents: boolean;
  agent: any;
}) {
  const router = useRouter();

  useEffect(() => {
    if (hasFetchedAgents && !agent) {
      router.replace("/");
    }
  }, [agent, hasFetchedAgents, router]);
}
