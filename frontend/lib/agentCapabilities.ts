import type {
  AgentCapabilities,
  AgentConfig,
  AgentSessionBindingWriteMode,
} from "@/store/agents";

const SHARED_SESSION_BINDING_URI = "urn:a2a:session-binding/v1";
const LEGACY_SHARED_SESSION_BINDING_URI = "urn:shared-a2a:session-binding:v1";
const SHARED_SESSION_ID_FIELD = "metadata.shared.session.id";

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const asArray = (value: unknown): unknown[] =>
  Array.isArray(value) ? value : [];

export const extractAgentCapabilitiesFromCard = (
  card: Record<string, unknown> | null | undefined,
): AgentCapabilities | null => {
  const capabilities = asRecord(card?.capabilities);
  const extensions = asArray(capabilities?.extensions);
  const sessionBindingExtension = extensions.find((candidate) => {
    const extension = asRecord(candidate);
    return (
      extension?.uri === SHARED_SESSION_BINDING_URI ||
      extension?.uri === LEGACY_SHARED_SESSION_BINDING_URI
    );
  });

  if (!sessionBindingExtension) {
    return {
      sessionBinding: {
        declared: false,
        mode: "compat_fallback",
        uri: null,
        metadataField: null,
      },
    };
  }

  const extension = asRecord(sessionBindingExtension);
  const params = asRecord(extension?.params);
  const uri = typeof extension?.uri === "string" ? extension.uri : null;
  const metadataField =
    typeof params?.metadata_field === "string" ? params.metadata_field : null;

  const mode: AgentSessionBindingWriteMode =
    uri === SHARED_SESSION_BINDING_URI &&
    metadataField === SHARED_SESSION_ID_FIELD
      ? "declared_contract"
      : "compat_fallback";

  return {
    sessionBinding: {
      declared: true,
      mode,
      uri,
      metadataField,
    },
  };
};

export const getAgentSessionBindingWriteMode = (
  agent: Pick<AgentConfig, "capabilities"> | null | undefined,
): AgentSessionBindingWriteMode =>
  agent?.capabilities?.sessionBinding?.mode ?? "unknown";
