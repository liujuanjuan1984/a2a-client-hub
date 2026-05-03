import {
  DEFAULT_RUNTIME_STATUS_CONTRACT,
  normalizeRuntimeState,
} from "@/lib/api/chat-utils";

const pickDisplayMessage = (
  details: Record<string, unknown> | null | undefined,
): string | null =>
  (typeof details?.displayMessage === "string" && details.displayMessage) ||
  (typeof details?.display_message === "string" && details.display_message) ||
  (typeof details?.description === "string" && details.description) ||
  (typeof (details?.request as { description?: unknown } | undefined)
    ?.description === "string" &&
    (details?.request as { description: string }).description) ||
  null;

export const buildCanonicalInterrupt = (
  interrupt?: Record<string, unknown>,
): Record<string, unknown> | null => {
  if (!interrupt) {
    return null;
  }
  const requestId =
    typeof interrupt.requestId === "string" ? interrupt.requestId : null;
  const type = typeof interrupt.type === "string" ? interrupt.type : null;
  if (!requestId || !type) {
    return null;
  }
  const phase =
    typeof interrupt.phase === "string"
      ? interrupt.phase.toLowerCase()
      : "asked";
  if (phase === "resolved") {
    return {
      requestId,
      type,
      phase: "resolved",
      resolution:
        typeof interrupt.resolution === "string"
          ? interrupt.resolution
          : "replied",
      source: "stream",
    };
  }

  const details =
    interrupt.details && typeof interrupt.details === "object"
      ? (interrupt.details as Record<string, unknown>)
      : null;
  if (type === "permission") {
    return {
      requestId,
      type,
      phase: "asked",
      source: "stream",
      details: {
        permission:
          typeof details?.permission === "string" ? details.permission : null,
        patterns: Array.isArray(details?.patterns) ? details.patterns : [],
        displayMessage: pickDisplayMessage(details),
      },
    };
  }
  if (type === "permissions") {
    return {
      requestId,
      type,
      phase: "asked",
      source: "stream",
      details: {
        permissions:
          details?.permissions && typeof details.permissions === "object"
            ? details.permissions
            : null,
        displayMessage: pickDisplayMessage(details),
      },
    };
  }
  if (type === "elicitation") {
    return {
      requestId,
      type,
      phase: "asked",
      source: "stream",
      details: {
        displayMessage: pickDisplayMessage(details),
        serverName:
          typeof details?.serverName === "string" ? details.serverName : null,
        mode: typeof details?.mode === "string" ? details.mode : null,
        requestedSchema: details?.requestedSchema ?? null,
        url: typeof details?.url === "string" ? details.url : null,
        elicitationId:
          typeof details?.elicitationId === "string"
            ? details.elicitationId
            : null,
        meta:
          details?.meta && typeof details.meta === "object"
            ? details.meta
            : null,
      },
    };
  }

  const rawQuestions =
    Array.isArray(details?.questions) && details?.questions
      ? details.questions
      : [];
  return {
    requestId,
    type: "question",
    phase: "asked",
    source: "stream",
    details: {
      displayMessage: pickDisplayMessage(details),
      questions: rawQuestions.map((question) => {
        const record =
          question && typeof question === "object"
            ? (question as Record<string, unknown>)
            : {};
        const options = Array.isArray(record.options) ? record.options : [];
        return {
          header:
            typeof record.header === "string"
              ? record.header
              : typeof record.title === "string"
                ? record.title
                : null,
          question:
            typeof record.question === "string"
              ? record.question
              : typeof record.prompt === "string"
                ? record.prompt
                : typeof record.message === "string"
                  ? record.message
                  : "",
          description:
            typeof record.description === "string" ? record.description : null,
          options: options.map((option) => {
            const optionRecord =
              option && typeof option === "object"
                ? (option as Record<string, unknown>)
                : {};
            return {
              label:
                typeof optionRecord.label === "string"
                  ? optionRecord.label
                  : "",
              value:
                typeof optionRecord.value === "string"
                  ? optionRecord.value
                  : null,
              description:
                typeof optionRecord.description === "string"
                  ? optionRecord.description
                  : null,
            };
          }),
        };
      }),
    },
  };
};

export const buildStatusUpdatePayload = (input: {
  state: string;
  seq?: number;
  messageId?: string;
  completionPhase?: string;
  interrupt?: Record<string, unknown>;
}) => {
  const canonicalInterrupt = buildCanonicalInterrupt(input.interrupt);
  const normalizedState = normalizeRuntimeState(input.state);
  return {
    statusUpdate: {
      status: { state: input.state },
      metadata: {
        shared: {
          ...(input.interrupt ? { interrupt: input.interrupt } : {}),
          stream: {
            ...(input.seq !== undefined ? { seq: input.seq } : {}),
            ...(input.messageId ? { messageId: input.messageId } : {}),
            ...(input.completionPhase
              ? { completionPhase: input.completionPhase }
              : {}),
          },
        },
      },
    },
    version: "v1",
    runtimeStatus: {
      state: normalizedState,
      isFinal: DEFAULT_RUNTIME_STATUS_CONTRACT.terminalStates
        .map((item) => normalizeRuntimeState(item))
        .includes(normalizedState),
      ...(canonicalInterrupt ? { interrupt: canonicalInterrupt } : {}),
      ...(input.seq !== undefined ? { seq: input.seq } : {}),
      ...(input.completionPhase?.trim().toLowerCase() === "persisted"
        ? { completionPhase: "persisted" }
        : {}),
    },
  };
};

export const buildTextArtifactUpdatePayload = ({
  messageId,
  agentMessageId,
  text,
  eventId,
  seq,
  source = "assistant_text",
  artifactId,
}: {
  messageId?: string;
  agentMessageId?: string;
  text: string;
  eventId: string;
  seq: number;
  source?: string;
  artifactId?: string;
}) => {
  const resolvedMessageId = messageId ?? agentMessageId ?? "";
  const resolvedArtifactId = artifactId ?? `${resolvedMessageId}:stream:${seq}`;
  return {
    artifactUpdate: {
    op: "append",
    artifact: {
      artifactId: resolvedArtifactId,
      parts: [{ text }],
      metadata: {
        shared: {
          stream: {
            blockType: "text",
            source,
            messageId: resolvedMessageId,
            eventId,
            seq,
          },
        },
      },
    },
  },
  version: "v1",
  streamBlock: {
    eventId,
    eventIdSource: "upstream",
    messageIdSource: "upstream",
    seq,
    artifactId: resolvedArtifactId,
    blockId: `${resolvedMessageId}:primary_text`,
    laneId: "primary_text",
    blockType: "text",
    op: "append",
    messageId: resolvedMessageId,
    delta: text,
    done: false,
  },
  };
};
