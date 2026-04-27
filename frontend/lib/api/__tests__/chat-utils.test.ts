import {
  DEFAULT_RUNTIME_STATUS_CONTRACT,
  extractRuntimeStatusEvent,
  extractSessionMeta,
  isInputRequiredRuntimeState,
  normalizeRuntimeState,
} from "@/lib/api/chat-utils";

describe("runtime status contract", () => {
  it("normalizes declared runtime status aliases", () => {
    expect(normalizeRuntimeState("input_required")).toBe("input-required");
    expect(normalizeRuntimeState("canceled")).toBe("cancelled");
    expect(normalizeRuntimeState("success")).toBe("completed");
    expect(normalizeRuntimeState("TASK_STATE_INPUT_REQUIRED")).toBe(
      "input-required",
    );
    expect(normalizeRuntimeState("TASK_STATE_CANCELED")).toBe("cancelled");
  });

  it("uses capability-provided aliases when available", () => {
    const customContract = {
      ...DEFAULT_RUNTIME_STATUS_CONTRACT,
      aliases: {
        ...DEFAULT_RUNTIME_STATUS_CONTRACT.aliases,
        approval_needed: "input-required",
      },
    };

    expect(normalizeRuntimeState("approval_needed", customContract)).toBe(
      "input-required",
    );
    expect(isInputRequiredRuntimeState("approval_needed", customContract)).toBe(
      true,
    );
  });

  it("preserves unknown runtime status tokens", () => {
    expect(normalizeRuntimeState("waiting-human")).toBe("waiting-human");
  });

  it("canonicalizes runtime status events", () => {
    expect(
      extractRuntimeStatusEvent({
        statusUpdate: {
          status: { state: "TASK_STATE_INPUT_REQUIRED" },
        },
      }),
    ).toEqual({
      state: "input-required",
      isFinal: true,
      interrupt: null,
      seq: null,
      completionPhase: null,
      messageId: null,
    });
  });

  it("extracts shared stream turn identity from lifecycle event properties", () => {
    expect(
      extractSessionMeta({
        artifactUpdate: {
          metadata: {
            shared: {
              stream: {
                thread_id: "thread-1",
                turn_id: "turn-2",
              },
            },
          },
        },
      }),
    ).toEqual({
      provider: undefined,
      externalSessionId: undefined,
      streamThreadId: "thread-1",
      streamTurnId: "turn-2",
      transport: undefined,
      inputModes: undefined,
      outputModes: undefined,
    });
  });

  it("treats interactive runtime states as input-required family", () => {
    expect(isInputRequiredRuntimeState("input-required")).toBe(true);
    expect(isInputRequiredRuntimeState("auth_required")).toBe(true);
    expect(isInputRequiredRuntimeState("completed")).toBe(false);
  });

  it("exports the default v1 runtime status contract", () => {
    expect(DEFAULT_RUNTIME_STATUS_CONTRACT.version).toBe("v1");
    expect(DEFAULT_RUNTIME_STATUS_CONTRACT.terminalStates).toContain(
      "input-required",
    );
    expect(DEFAULT_RUNTIME_STATUS_CONTRACT.aliases.canceled).toBe("cancelled");
  });
});
