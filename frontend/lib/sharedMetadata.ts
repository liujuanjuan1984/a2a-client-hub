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

const getMetadataRecord = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
) => {
  const metadata = asRecord(payloadOrMetadata?.metadata);
  return metadata ?? payloadOrMetadata ?? null;
};

const getSharedMetadataSection = (
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

export const pickSharedMetadataSections = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
  sections: ("interrupt" | "model" | "session" | "stream" | "usage")[],
) => {
  const resolved: Record<string, unknown> = {};
  sections.forEach((section) => {
    const sharedSection = getSharedMetadataSection(payloadOrMetadata, section);
    if (sharedSection) {
      resolved[section] = { ...sharedSection };
    }
  });

  return Object.keys(resolved).length > 0 ? { shared: resolved } : {};
};

export const getPreferredInterruptMetadata = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
) => getSharedMetadataSection(payloadOrMetadata, "interrupt");

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

export const readSharedStreamIdentity = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
) => {
  const stream = getSharedMetadataSection(payloadOrMetadata, "stream");
  return {
    threadId: pickString(stream, ["thread_id", "threadId"]),
    turnId: pickString(stream, ["turn_id", "turnId"]),
  };
};

export const withSharedStreamIdentity = (
  metadata: Record<string, unknown> | null | undefined,
  identity: {
    threadId?: string | null;
    turnId?: string | null;
  } | null,
) => {
  const nextMetadata = { ...(metadata ?? {}) };
  const nextShared = asRecord(nextMetadata.shared)
    ? { ...(nextMetadata.shared as Record<string, unknown>) }
    : {};
  const nextStream = asRecord(nextShared.stream)
    ? { ...(nextShared.stream as Record<string, unknown>) }
    : {};

  const threadId = identity?.threadId?.trim() ?? "";
  const turnId = identity?.turnId?.trim() ?? "";

  if (threadId) {
    nextStream.thread_id = threadId;
  } else {
    delete nextStream.thread_id;
    delete nextStream.threadId;
  }
  if (turnId) {
    nextStream.turn_id = turnId;
  } else {
    delete nextStream.turn_id;
    delete nextStream.turnId;
  }

  if (Object.keys(nextStream).length > 0) {
    nextShared.stream = nextStream;
  } else {
    delete nextShared.stream;
  }

  if (Object.keys(nextShared).length > 0) {
    nextMetadata.shared = nextShared;
  } else {
    delete nextMetadata.shared;
  }

  return nextMetadata;
};

export const withoutSharedSessionBinding = (
  metadata: Record<string, unknown> | null | undefined,
  options?: {
    keepSharedStream?: boolean;
  },
) => {
  const nextMetadata = { ...(metadata ?? {}) };
  const nextShared = asRecord(nextMetadata.shared)
    ? { ...(nextMetadata.shared as Record<string, unknown>) }
    : null;

  if (nextShared) {
    delete nextShared.session;
    if (!options?.keepSharedStream) {
      delete nextShared.stream;
    }
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
