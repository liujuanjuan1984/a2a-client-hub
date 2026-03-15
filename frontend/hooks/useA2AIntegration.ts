import { useA2AHandlers } from "./useA2AHandlers";
import { useA2AResolutionWatcher } from "./useA2AResolutionWatcher";
import { useA2AState } from "./useA2AState";

import {
  type PendingRuntimeInterrupt,
  type ResolvedRuntimeInterrupt,
} from "@/lib/api/chat-utils";
import { type AgentConfig } from "@/store/agents";
import { useChatStore } from "@/store/chat";

export function useA2AIntegration({
  conversationId,
  agent,
}: {
  conversationId: string | undefined;
  agent: AgentConfig | undefined;
}) {
  const session = useChatStore((state) =>
    conversationId ? state.sessions[conversationId] : undefined,
  );
  const pendingInterrupt = (session?.pendingInterrupt ??
    null) as PendingRuntimeInterrupt | null;
  const lastResolvedInterrupt = (session?.lastResolvedInterrupt ??
    null) as ResolvedRuntimeInterrupt | null;

  const {
    interruptAction,
    setInterruptAction,
    questionAnswers,
    setQuestionAnswers,
  } = useA2AState(pendingInterrupt);

  const { acknowledgeLocalInterruptResolution } = useA2AResolutionWatcher(
    lastResolvedInterrupt,
  );

  const handlers = useA2AHandlers({
    conversationId,
    agent,
    pendingInterrupt,
    questionAnswers,
    setQuestionAnswers,
    setInterruptAction,
    acknowledgeLocalInterruptResolution,
  });

  return {
    pendingInterrupt,
    interruptAction,
    questionAnswers,
    ...handlers,
  };
}
