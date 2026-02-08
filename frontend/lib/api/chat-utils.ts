export type ChatRole = "user" | "agent" | "system";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  status?: "streaming" | "done";
  streamChunks?: StreamChunkRecord[];
};

export type StreamChunkRecord = {
  text: string;
  append: boolean;
};

export type StreamChunk = {
  text: string;
  append: boolean;
  done?: boolean;
};

const coerceStringArray = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "string")
    ? (value as string[])
    : undefined;

export const extractSessionMeta = (data: Record<string, unknown>) => {
  const contextId =
    typeof data.context_id === "string"
      ? data.context_id
      : typeof data.contextId === "string"
        ? data.contextId
        : null;
  const transport =
    typeof data.transport === "string" ? data.transport : undefined;
  const inputModes =
    coerceStringArray(data.input_modes) ?? coerceStringArray(data.inputModes);
  const outputModes =
    coerceStringArray(data.output_modes) ?? coerceStringArray(data.outputModes);

  return {
    contextId,
    transport,
    inputModes,
    outputModes,
  };
};

export const extractRuntimeStatus = (data: Record<string, unknown>) => {
  if (data.kind !== "status-update") {
    return null;
  }
  const status = data.status as { state?: unknown } | undefined;
  if (status && typeof status.state === "string") {
    return status.state;
  }
  return null;
};

const extractTextFromParts = (parts: unknown[]) =>
  parts
    .map((part) => {
      if (!part || typeof part !== "object") {
        return null;
      }
      const typed = part as { kind?: unknown; text?: unknown };
      if (typed.kind === "text" && typeof typed.text === "string") {
        return typed.text;
      }
      return null;
    })
    .filter((item): item is string => Boolean(item))
    .join("");

export const extractStreamChunk = (
  data: Record<string, unknown>,
): StreamChunk | null => {
  if (data.kind === "artifact-update") {
    const artifact = data.artifact as { parts?: unknown[] } | undefined;
    const parts = Array.isArray(artifact?.parts) ? artifact.parts : [];
    const text = extractTextFromParts(parts);
    if (!text) {
      return null;
    }
    let appendFlag = true;
    if (typeof data.append === "boolean") {
      appendFlag = data.append;
    } else {
      const artifactAppend = (artifact as { append?: unknown }).append;
      if (typeof artifactAppend === "boolean") {
        appendFlag = artifactAppend;
      }
    }
    return {
      text,
      append: appendFlag,
      done: data.lastChunk === true,
    };
  }

  if (typeof data.content === "string") {
    return { text: data.content, append: true };
  }
  if (typeof data.message === "string") {
    return { text: data.message, append: true };
  }
  return null;
};
