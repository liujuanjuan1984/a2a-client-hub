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

const randomHex = (length: number) => {
  let output = "";
  while (output.length < length) {
    output += Math.random().toString(16).slice(2);
  }
  return output.slice(0, length);
};

export const generateUuid = (): string => {
  const fn = globalThis.crypto?.randomUUID;
  if (typeof fn === "function") {
    return fn.call(globalThis.crypto);
  }
  const part1 = randomHex(8);
  const part2 = randomHex(4);
  const part3 = `4${randomHex(3)}`;
  const variant = (8 + Math.floor(Math.random() * 4)).toString(16);
  const part4 = `${variant}${randomHex(3)}`;
  const part5 = randomHex(12);
  return `${part1}-${part2}-${part3}-${part4}-${part5}`;
};
