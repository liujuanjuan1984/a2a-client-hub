const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const normalizeBindingValue = (value: unknown): string | null => {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized || null;
};

export const getInvokeMetadataBindings = (
  metadata: Record<string, unknown> | null | undefined,
) => {
  const shared = asRecord(metadata?.shared);
  const invoke = asRecord(shared?.invoke);
  const bindings = asRecord(invoke?.bindings);
  if (!bindings) {
    return {};
  }

  return Object.entries(bindings).reduce<Record<string, string>>(
    (acc, [key, value]) => {
      const normalized = normalizeBindingValue(value);
      if (!normalized) {
        return acc;
      }
      acc[key] = normalized;
      return acc;
    },
    {},
  );
};

export const withInvokeMetadataBindings = (
  metadata: Record<string, unknown> | null | undefined,
  bindings: Record<string, string>,
): Record<string, unknown> => {
  const nextMetadata = { ...(metadata ?? {}) };
  const nextShared = asRecord(nextMetadata.shared)
    ? { ...(nextMetadata.shared as Record<string, unknown>) }
    : {};
  const nextInvoke = asRecord(nextShared.invoke)
    ? { ...(nextShared.invoke as Record<string, unknown>) }
    : {};

  const normalizedBindings = Object.entries(bindings).reduce<
    Record<string, string>
  >((acc, [key, value]) => {
    const normalizedKey = key.trim();
    const normalizedValue = normalizeBindingValue(value);
    if (!normalizedKey || !normalizedValue) {
      return acc;
    }
    acc[normalizedKey] = normalizedValue;
    return acc;
  }, {});

  if (Object.keys(normalizedBindings).length > 0) {
    nextInvoke.bindings = normalizedBindings;
    nextShared.invoke = nextInvoke;
    nextMetadata.shared = nextShared;
    return nextMetadata;
  }

  delete nextInvoke.bindings;
  if (Object.keys(nextInvoke).length > 0) {
    nextShared.invoke = nextInvoke;
  } else {
    delete nextShared.invoke;
  }
  if (Object.keys(nextShared).length > 0) {
    nextMetadata.shared = nextShared;
  } else {
    delete nextMetadata.shared;
  }
  return nextMetadata;
};
