import { type SessionContinueBinding } from "@/lib/api/sessions";

export const buildContinueBindingPayload = (
  agentId: string,
  binding: SessionContinueBinding,
) => {
  const metadata = binding.metadata || {};
  return {
    agentId,
    source: binding.source,
    provider:
      typeof metadata.provider === "string" ? metadata.provider : undefined,
    externalSessionId:
      typeof metadata.externalSessionId === "string"
        ? metadata.externalSessionId
        : undefined,
    contextId:
      typeof metadata.contextId === "string" ? metadata.contextId : undefined,
  };
};
