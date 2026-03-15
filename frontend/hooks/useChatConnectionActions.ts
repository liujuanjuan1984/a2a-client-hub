import { useCallback } from "react";

import { useValidateAgentMutation } from "@/hooks/useAgentsCatalogQuery";
import { blurActiveElement } from "@/lib/focus";
import { toast } from "@/lib/toast";
import { type AgentConfig } from "@/store/agents";

export function useChatConnectionActions(agent: AgentConfig | undefined) {
  const validateAgentMutation = useValidateAgentMutation();
  const activeAgentId = agent?.id ?? null;

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

  return {
    onTest: handleTest,
    testingConnection: validateAgentMutation.isPending,
  };
}
