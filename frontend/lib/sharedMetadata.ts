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
) => getSharedMetadataSection(payloadOrMetadata, "session");

export const readSharedStreamIdentity = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
) => {
  const stream = getSharedMetadataSection(payloadOrMetadata, "stream");
  return {
    threadId: pickString(stream, ["threadId"]),
    turnId: pickString(stream, ["turnId"]),
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
    nextStream.threadId = threadId;
  } else {
    delete nextStream.threadId;
  }
  if (turnId) {
    nextStream.turnId = turnId;
  } else {
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

  delete nextMetadata.externalSessionId;
  delete nextMetadata.provider;
  return nextMetadata;
};

export const withSharedSessionBinding = (
  metadata: Record<string, unknown> | null | undefined,
  binding: {
    provider?: string | null;
    externalSessionId?: string | null;
  } | null,
) => {
  const nextMetadata = withoutSharedSessionBinding(metadata, {
    keepSharedStream: true,
  });
  const nextShared = asRecord(nextMetadata.shared)
    ? { ...(nextMetadata.shared as Record<string, unknown>) }
    : {};
  const nextSession = asRecord(nextShared.session)
    ? { ...(nextShared.session as Record<string, unknown>) }
    : {};

  const provider = binding?.provider?.trim() ?? "";
  const externalSessionId = binding?.externalSessionId?.trim() ?? "";

  if (externalSessionId) {
    nextSession.id = externalSessionId;
  }
  if (provider) {
    nextSession.provider = provider;
  }

  if (Object.keys(nextSession).length > 0) {
    nextShared.session = nextSession;
  } else {
    delete nextShared.session;
  }

  if (Object.keys(nextShared).length > 0) {
    nextMetadata.shared = nextShared;
  } else {
    delete nextMetadata.shared;
  }

  return nextMetadata;
};

export const readSharedSessionBinding = (
  payloadOrMetadata: Record<string, unknown> | null | undefined,
) => {
  const session = getPreferredSessionMetadata(payloadOrMetadata);
  return {
    provider: pickString(session, ["provider"]),
    externalSessionId: pickString(session, ["id"]),
  };
};
