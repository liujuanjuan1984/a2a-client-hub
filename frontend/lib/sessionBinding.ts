import { type SessionContinueBinding } from "@/lib/api/sessions";
import { pickOpencodeDirectoryMetadata } from "@/lib/opencodeMetadata";
import { readSharedSessionBinding } from "@/lib/sharedMetadata";

export const buildContinueBindingPayload = (
  agentId: string,
  binding: SessionContinueBinding,
) => {
  const metadata = binding.metadata || {};
  const sessionBinding = readSharedSessionBinding(metadata);
  const opencodeMetadata = pickOpencodeDirectoryMetadata(metadata);
  return {
    agentId,
    source: binding.source,
    provider: sessionBinding.provider ?? undefined,
    externalSessionId: sessionBinding.externalSessionId ?? undefined,
    ...(opencodeMetadata ? { metadata: opencodeMetadata } : {}),
  };
};
