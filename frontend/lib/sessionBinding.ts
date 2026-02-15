import { type SessionContinueBinding } from "@/lib/api/sessions";

export const resolveCanonicalSessionId = (
  requestedSessionId: string,
  binding: Pick<SessionContinueBinding, "session_id">,
) => {
  const candidate =
    typeof binding.session_id === "string" ? binding.session_id.trim() : "";
  return candidate || requestedSessionId;
};

export const buildContinueBindingPayload = (
  agentId: string,
  binding: SessionContinueBinding,
) => ({
  agentId,
  conversationId: binding.conversationId ?? undefined,
  provider: binding.provider ?? undefined,
  externalSessionId: binding.externalSessionId ?? undefined,
  contextId: binding.contextId ?? undefined,
  metadata: binding.metadata,
});
