import { type SessionContinueBinding } from "@/lib/api/sessions";

export const buildContinueBindingPayload = (
  agentId: string,
  binding: SessionContinueBinding,
) => ({
  agentId,
  source: binding.source,
  provider: binding.provider ?? undefined,
  externalSessionId: binding.externalSessionId ?? undefined,
  contextId: binding.contextId ?? undefined,
});
