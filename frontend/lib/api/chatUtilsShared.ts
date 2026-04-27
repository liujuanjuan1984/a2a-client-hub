export const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

export const pickString = (
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

export const pickRawString = (
  source: Record<string, unknown> | null,
  keys: string[],
): string | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string") {
      return value;
    }
  }
  return null;
};

export const pickInt = (
  source: Record<string, unknown> | null,
  keys: string[],
): number | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "number" && Number.isInteger(value)) {
      return value;
    }
    if (
      typeof value === "string" &&
      value.trim().length > 0 &&
      /^-?\d+$/.test(value.trim())
    ) {
      return Number.parseInt(value.trim(), 10);
    }
  }
  return null;
};

export const resolveNestedValue = (
  source: Record<string, unknown> | null,
  path: string[],
): unknown => {
  if (!source) return null;
  let current: unknown = source;
  for (const key of path) {
    const record = asRecord(current);
    if (!record) {
      return null;
    }
    current = record[key];
  }
  return current;
};

export const pickNestedRawString = (
  source: Record<string, unknown> | null,
  paths: string[][],
): string | null => {
  if (!source) return null;
  for (const path of paths) {
    const current = resolveNestedValue(source, path);
    if (typeof current === "string") {
      const trimmed = current.trim();
      if (trimmed) {
        return trimmed;
      }
    }
  }
  return null;
};

export const pickFirstArray = (
  source: Record<string, unknown> | null,
  paths: string[][],
): unknown[] => {
  if (!source) return [];
  for (const path of paths) {
    const current = resolveNestedValue(source, path);
    if (Array.isArray(current)) {
      return current;
    }
  }
  return [];
};

export const pickInteger = (
  source: Record<string, unknown> | null,
  keys: string[],
): number | null => {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (
      typeof value === "number" &&
      Number.isFinite(value) &&
      Number.isInteger(value)
    ) {
      return value;
    }
    if (typeof value === "string" && /^-?\d+$/.test(value.trim())) {
      return Number(value.trim());
    }
  }
  return null;
};

export const coerceStringArray = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "string")
    ? (value as string[])
    : undefined;

export const extractTextFromParts = (parts: unknown[]) =>
  parts
    .map((part) => {
      if (!part || typeof part !== "object") {
        return null;
      }
      const typed = part as {
        text?: unknown;
      };
      if (typeof typed.text === "string") {
        return typed.text;
      }
      return null;
    })
    .filter((item): item is string => Boolean(item))
    .join("");

const sortSerializableValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => sortSerializableValue(item));
  }
  if (value && typeof value === "object") {
    return Object.keys(value as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((acc, key) => {
        acc[key] = sortSerializableValue(
          (value as Record<string, unknown>)[key],
        );
        return acc;
      }, {});
  }
  return value;
};

export const serializeStructuredStreamData = (
  value: unknown,
): string | null => {
  if (value === undefined || value === null) {
    return null;
  }
  try {
    return JSON.stringify(sortSerializableValue(value));
  } catch {
    return JSON.stringify(String(value));
  }
};
