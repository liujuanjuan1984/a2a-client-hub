const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const pickString = (
  source: Record<string, unknown> | null,
  keys: string[],
): string | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
};

export const getMetadataRecord = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
) => {
  const metadata = asRecord(payloadOrMetadata?.metadata);
  return metadata ?? payloadOrMetadata ?? null;
};

export const getSharedMetadataSection = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
  section: "interrupt" | "model" | "session" | "stream" | "usage",
) => {
  const metadata = getMetadataRecord(payloadOrMetadata);
  const shared = asRecord(metadata?.shared);
  return asRecord(shared?.[section]);
};

export const mergeSharedMetadataSection = (
  values: (Record<string, unknown> | null | undefined)[],
  section: "interrupt" | "model" | "session" | "stream" | "usage",
) => {
  const resolved: Record<string, unknown> = {};
  values.forEach((value) => {
    const sharedSection = getSharedMetadataSection(value, section);
    if (sharedSection) {
      Object.assign(resolved, sharedSection);
    }
  });
  return Object.keys(resolved).length > 0 ? resolved : null;
};

export const getPreferredInterruptMetadata = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
) => {
  const canonical = getSharedMetadataSection(payloadOrMetadata, "interrupt");
  if (canonical) {
    return canonical;
  }
  const metadata = getMetadataRecord(payloadOrMetadata);
  return asRecord(metadata?.interrupt);
};

export const getPreferredSessionMetadata = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
) => {
  const metadata = getMetadataRecord(payloadOrMetadata);
  const canonical = getSharedMetadataSection(payloadOrMetadata, "session");
  if (canonical) {
    const merged = { ...canonical };
    if (pickString(merged, ["id", "externalSessionId"]) == null) {
      const sessionId = pickString(metadata, ["externalSessionId"]);
      if (sessionId) {
        merged.id = sessionId;
      }
    }
    if (pickString(merged, ["provider"]) == null) {
      const provider = pickString(metadata, ["provider"]);
      if (provider) {
        merged.provider = provider;
      }
    }
    return merged;
  }
  const legacy: Record<string, unknown> = {};
  const sessionId = pickString(metadata, ["externalSessionId"]);
  const provider = pickString(metadata, ["provider"]);
  if (sessionId) {
    legacy.id = sessionId;
  }
  if (provider) {
    legacy.provider = provider;
  }
  return Object.keys(legacy).length > 0 ? legacy : null;
};

export const withSharedSessionBinding = (
  metadata: Record<string, unknown> | null | undefined,
  sessionId: string | null,
  provider?: string | null,
) => {
  const nextMetadata = { ...(metadata ?? {}) };
  const nextShared = asRecord(nextMetadata.shared)
    ? { ...(nextMetadata.shared as Record<string, unknown>) }
    : {};

  const normalizedSessionId =
    typeof sessionId === "string" ? sessionId.trim() : "";
  if (normalizedSessionId) {
    const nextSession = asRecord(nextShared.session)
      ? { ...(nextShared.session as Record<string, unknown>) }
      : {};
    nextSession.id = normalizedSessionId;
    const normalizedProvider =
      typeof provider === "string" ? provider.trim().toLowerCase() : "";
    if (normalizedProvider) {
      nextSession.provider = normalizedProvider;
    } else {
      delete nextSession.provider;
    }
    nextShared.session = nextSession;
    nextMetadata.shared = nextShared;
    return nextMetadata;
  }

  delete nextShared.session;
  if (Object.keys(nextShared).length > 0) {
    nextMetadata.shared = nextShared;
  } else {
    delete nextMetadata.shared;
  }
  return nextMetadata;
};

export const withoutSharedSessionBinding = (
  metadata: Record<string, unknown> | null | undefined,
) => {
  const nextMetadata = { ...(metadata ?? {}) };
  const nextShared = asRecord(nextMetadata.shared)
    ? { ...(nextMetadata.shared as Record<string, unknown>) }
    : null;

  if (nextShared) {
    delete nextShared.session;
    if (Object.keys(nextShared).length > 0) {
      nextMetadata.shared = nextShared;
    } else {
      delete nextMetadata.shared;
    }
  }

  delete nextMetadata.provider;
  delete nextMetadata.externalSessionId;
  return nextMetadata;
};

export const readSharedSessionBinding = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
) => {
  const session = getPreferredSessionMetadata(payloadOrMetadata);
  return {
    provider: pickString(session, ["provider"]),
    externalSessionId: pickString(session, ["id", "externalSessionId"]),
  };
};
