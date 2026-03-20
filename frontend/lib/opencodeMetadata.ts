const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

export const getOpencodeDirectory = (
  metadata: Record<string, unknown> | null | undefined,
): string | null => {
  const opencode = asRecord(metadata?.opencode);
  const directory =
    typeof opencode?.directory === "string" ? opencode.directory.trim() : "";
  return directory || null;
};

export const withOpencodeDirectory = (
  metadata: Record<string, unknown> | null | undefined,
  directory: string | null,
): Record<string, unknown> => {
  const nextMetadata = { ...(metadata ?? {}) };
  const nextOpencode = asRecord(nextMetadata.opencode)
    ? { ...(nextMetadata.opencode as Record<string, unknown>) }
    : {};
  const normalizedDirectory =
    typeof directory === "string" ? directory.trim() : "";

  if (normalizedDirectory) {
    nextOpencode.directory = normalizedDirectory;
    nextMetadata.opencode = nextOpencode;
    return nextMetadata;
  }

  delete nextOpencode.directory;
  if (Object.keys(nextOpencode).length > 0) {
    nextMetadata.opencode = nextOpencode;
  } else {
    delete nextMetadata.opencode;
  }
  return nextMetadata;
};

export const pickOpencodeDirectoryMetadata = (
  metadata: Record<string, unknown> | null | undefined,
) => {
  const directory = getOpencodeDirectory(metadata);
  return directory ? { opencode: { directory } } : undefined;
};
