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
    provider: sessionBinding.provider ?? undefined,
    externalSessionId: sessionBinding.externalSessionId ?? undefined,
    workingDirectory: binding.workingDirectory ?? undefined,
  };
};
