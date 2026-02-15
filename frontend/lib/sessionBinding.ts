import { type SessionContinueBinding } from "@/lib/api/sessions";

export const buildContinueBindingPayload = (
  agentId: string,
  binding: SessionContinueBinding,
) => ({
  agentId,
  source: binding.source,
  conversationId: binding.conversationId ?? undefined,
  provider: binding.provider ?? undefined,
  externalSessionId: binding.externalSessionId ?? undefined,
  contextId: binding.contextId ?? undefined,
  metadata: binding.metadata,
});
