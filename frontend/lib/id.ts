/**
 * Generates a unique ID for UI elements and temporary keys.
 * Centralized as part of Issue #46 to remove redundancy.
 */
export const generateId = (prefix = ""): string => {
  const timestamp = Date.now().toString(36);
  const randomPart = Math.random().toString(36).slice(2, 8);
  return prefix
    ? `${prefix}-${timestamp}${randomPart}`
    : `${timestamp}${randomPart}`;
};
