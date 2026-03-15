import { getSharedModelSelection, type AgentSession } from "@/lib/chat-utils";

export function useChatStates({
  session,
}: {
  session: AgentSession | undefined;
}) {
  const pendingInterrupt = session?.pendingInterrupt ?? null;
  const lastResolvedInterrupt = session?.lastResolvedInterrupt ?? null;
  const selectedModel = getSharedModelSelection(session?.metadata);

  return {
    pendingInterrupt,
    lastResolvedInterrupt,
    selectedModel,
  };
}
