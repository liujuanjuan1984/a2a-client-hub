type ParsedComposerInput =
  | {
      kind: "message";
      text: string;
    }
  | {
      kind: "command";
      command: string;
      arguments: string;
      prompt: string;
    };

const restoreEscapedSlash = (value: string) => {
  const trimmedStart = value.trimStart();
  const leadingLength = value.length - trimmedStart.length;
  return `${value.slice(0, leadingLength)}/${trimmedStart.slice(2)}`;
};

export const parseComposerInput = (value: string): ParsedComposerInput => {
  const trimmedStart = value.trimStart();
  if (!trimmedStart.startsWith("/")) {
    return {
      kind: "message",
      text: value,
    };
  }

  if (trimmedStart.startsWith("//")) {
    return {
      kind: "message",
      text: restoreEscapedSlash(value),
    };
  }

  const normalized = trimmedStart.trim();
  const lines = normalized.split(/\r?\n/);
  const header = lines[0]?.trim() ?? "";
  const remainder = lines.slice(1).join("\n").trim();
  const firstWhitespaceIndex = header.search(/\s/);
  const command =
    firstWhitespaceIndex === -1
      ? header
      : header.slice(0, firstWhitespaceIndex);
  const argumentsText =
    firstWhitespaceIndex === -1
      ? ""
      : header.slice(firstWhitespaceIndex).trim();

  return {
    kind: "command",
    command,
    arguments: argumentsText,
    prompt: remainder,
  };
};
