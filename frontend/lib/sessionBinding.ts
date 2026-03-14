import { type SessionContinueBinding } from "@/lib/api/sessions";
import { readSharedSessionBinding } from "@/lib/sharedMetadata";

export const buildContinueBindingPayload = (
  agentId: string,
  binding: SessionContinueBinding,
) => {
  const metadata = binding.metadata || {};
  const sessionBinding = readSharedSessionBinding(metadata);
  return {
    agentId,
    source: binding.source,
    provider:
      sessionBinding.provider ??
      (typeof metadata.provider === "string" ? metadata.provider : undefined),
    externalSessionId:
      sessionBinding.externalSessionId ??
      (typeof metadata.externalSessionId === "string"
        ? metadata.externalSessionId
        : undefined),
    contextId:
      typeof metadata.contextId === "string" ? metadata.contextId : undefined,
  };
};
