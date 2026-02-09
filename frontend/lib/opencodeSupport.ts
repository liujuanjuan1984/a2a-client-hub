export const OPENCODE_SESSION_QUERY_URI =
  "urn:opencode-a2a:opencode-session-query/v1";

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;

export const supportsOpencodeSessionQuery = (card: unknown): boolean => {
  const root = asRecord(card);
  if (!root) return false;

  const capabilities = asRecord(root.capabilities);
  if (!capabilities) return false;

  const extensions = capabilities.extensions;
  if (!Array.isArray(extensions)) return false;

  return extensions.some((ext) => {
    const typed = asRecord(ext);
    if (!typed) return false;
    return typed.uri === OPENCODE_SESSION_QUERY_URI;
  });
};
