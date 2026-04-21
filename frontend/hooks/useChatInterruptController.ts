import { useCallback, useEffect, useRef, useState } from "react";

import {
  A2AExtensionCallError,
  rejectQuestionInterrupt,
  replyElicitationInterrupt,
  type ExtensionAgentSource,
  replyPermissionInterrupt,
  replyPermissionsInterrupt,
  replyQuestionInterrupt,
} from "@/lib/api/a2aExtensions";
import { type PendingRuntimeInterrupt } from "@/lib/api/chat-utils";
import { ApiRequestError } from "@/lib/api/client";
import { type ResolvedRuntimeInterruptRecord } from "@/lib/chat-utils";
import { toast } from "@/lib/toast";
import { normalizeWorkingDirectory } from "@/lib/workingDirectory";

const TERMINAL_INTERRUPT_ERROR_CODES = new Set([
  "interrupt_request_expired",
  "interrupt_request_not_found",
]);

type ResolvedInterruptKeyInput = {
  requestId: string;
  type: "permission" | "question" | "permissions" | "elicitation";
  resolution: "replied" | "rejected" | "expired";
};

export type InterruptActionMode = "ack-fast" | "transactional";

export type InterruptActionResult = {
  mode: InterruptActionMode;
  resolvedRequestId?: string;
};

type UseChatInterruptControllerParams = {
  activeAgentId?: string | null;
  agentSource?: ExtensionAgentSource | null;
  conversationId?: string;
  pendingInterrupt: PendingRuntimeInterrupt | null;
  lastResolvedInterrupt: ResolvedRuntimeInterruptRecord | null;
  pendingQuestionCount: number;
  workingDirectory?: string | null;
  clearPendingInterrupt: (conversationId: string, requestId?: string) => void;
  onPermissionReplyOverride?:
    | ((input: {
        requestId: string;
        reply: "once" | "always" | "reject";
      }) => Promise<InterruptActionResult>)
    | null;
  permissionReplySuccessMessage?: string | null;
};

export function useChatInterruptController({
  activeAgentId,
  agentSource,
  conversationId,
  pendingInterrupt,
  lastResolvedInterrupt,
  pendingQuestionCount,
  workingDirectory,
  clearPendingInterrupt,
  onPermissionReplyOverride,
  permissionReplySuccessMessage,
}: UseChatInterruptControllerParams) {
  const [interruptAction, setInterruptAction] = useState<string | null>(null);
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);
  const [structuredResponseInput, setStructuredResponseInput] =
    useState<string>("");
  const normalizedWorkingDirectory =
    normalizeWorkingDirectory(workingDirectory);
  const handledResolvedInterruptKeysRef = useRef<Set<string>>(new Set());
  const locallyAcknowledgedResolvedInterruptKeysRef = useRef<Set<string>>(
    new Set(),
  );
  const mountedAtRef = useRef(Date.now());

  const buildInterruptErrorMessage = useCallback((error: unknown) => {
    if (error instanceof ApiRequestError) {
      const codeSuffix = error.errorCode ? ` [${error.errorCode}]` : "";
      const upstreamMessage =
        error.upstreamError &&
        typeof error.upstreamError === "object" &&
        typeof error.upstreamError.message === "string"
          ? error.upstreamError.message
          : null;

      return upstreamMessage
        ? `${error.message}${codeSuffix}：${upstreamMessage}`
        : `${error.message}${codeSuffix}`;
    }

    if (error instanceof A2AExtensionCallError) {
      if (error.errorCode === "session_forbidden") {
        return error.message;
      }
      if (error.errorCode && !error.message.includes(error.errorCode)) {
        return `${error.message}: ${error.errorCode}`;
      }
      return error.message;
    }

    return error instanceof Error
      ? error.message
      : "Interrupt callback failed.";
  }, []);

  const getInterruptErrorCode = useCallback((error: unknown) => {
    if (
      error instanceof ApiRequestError ||
      error instanceof A2AExtensionCallError
    ) {
      return error.errorCode;
    }
    return null;
  }, []);

  const buildTerminalInterruptDismissMessage = useCallback(
    (errorCode: string | null) => {
      if (errorCode === "interrupt_request_expired") {
        return "The interrupt request expired and was removed.";
      }
      return "The interrupt request no longer exists and was removed.";
    },
    [],
  );

  const buildResolvedInterruptKey = useCallback(
    (interrupt: ResolvedInterruptKeyInput | null) =>
      interrupt
        ? `${interrupt.requestId}:${interrupt.type}:${interrupt.resolution}`
        : "",
    [],
  );

  const acknowledgeLocalInterruptResolution = useCallback(
    (
      requestId: string,
      interruptType: "permission" | "question" | "permissions" | "elicitation",
      resolution: "replied" | "rejected",
    ) => {
      locallyAcknowledgedResolvedInterruptKeysRef.current.add(
        buildResolvedInterruptKey({
          requestId,
          type: interruptType,
          resolution,
        }),
      );
    },
    [buildResolvedInterruptKey],
  );

  const buildResolvedInterruptFeedback = useCallback(
    (interrupt: ResolvedRuntimeInterruptRecord) => {
      if (interrupt.type === "permission") {
        if (interrupt.resolution === "expired") {
          return {
            title: "Interrupt resolved",
            message: "Authorization request expired and was closed.",
          };
        }
        return {
          title: "Interrupt resolved",
          message: "Authorization request was handled.",
        };
      }
      if (interrupt.type === "permissions") {
        if (interrupt.resolution === "expired") {
          return {
            title: "Interrupt resolved",
            message: "Permissions request expired and was closed.",
          };
        }
        return {
          title: "Interrupt resolved",
          message: "Permissions request was handled.",
        };
      }
      if (interrupt.type === "elicitation") {
        if (interrupt.resolution === "expired") {
          return {
            title: "Interrupt resolved",
            message:
              "Additional input request expired and the interrupt is closed.",
          };
        }
        if (interrupt.resolution === "rejected") {
          return {
            title: "Interrupt resolved",
            message:
              "Additional input request was declined and the interrupt is closed.",
          };
        }
        return {
          title: "Interrupt resolved",
          message: "Additional input submitted. Agent resumed.",
        };
      }
      if (interrupt.resolution === "expired") {
        return {
          title: "Interrupt resolved",
          message: "Question request expired and the interrupt is closed.",
        };
      }
      if (interrupt.resolution === "rejected") {
        return {
          title: "Interrupt resolved",
          message: "Question request was rejected and the interrupt is closed.",
        };
      }
      return {
        title: "Interrupt resolved",
        message: "Question answer received. Agent resumed.",
      };
    },
    [],
  );

  const runInterruptAction = useCallback(
    async (
      actionKey: string,
      executor: () => Promise<void>,
      successMessage: string,
      options?: {
        conversationId: string;
        requestId: string;
      },
    ) => {
      setInterruptAction(actionKey);
      try {
        await executor();
        toast.success("Action submitted", successMessage);
      } catch (error) {
        const errorCode = getInterruptErrorCode(error);
        if (
          options &&
          errorCode &&
          TERMINAL_INTERRUPT_ERROR_CODES.has(errorCode)
        ) {
          clearPendingInterrupt(options.conversationId, options.requestId);
          toast.info(
            "Interrupt closed",
            buildTerminalInterruptDismissMessage(errorCode),
          );
          return;
        }
        toast.error(
          "Interrupt callback failed",
          buildInterruptErrorMessage(error),
        );
      } finally {
        setInterruptAction(null);
      }
    },
    [
      buildInterruptErrorMessage,
      buildTerminalInterruptDismissMessage,
      clearPendingInterrupt,
      getInterruptErrorCode,
    ],
  );

  const finalizeInterruptAction = useCallback(
    ({
      actionResult,
      conversationId,
      requestId,
      interruptType,
      resolution,
    }: {
      actionResult: InterruptActionResult;
      conversationId: string;
      requestId: string;
      interruptType: "permission" | "question" | "permissions" | "elicitation";
      resolution: "replied" | "rejected";
    }) => {
      const resolvedRequestId = actionResult.resolvedRequestId ?? requestId;
      if (actionResult.mode === "ack-fast") {
        clearPendingInterrupt(conversationId, resolvedRequestId);
      }
      acknowledgeLocalInterruptResolution(requestId, interruptType, resolution);
      if (actionResult.mode === "transactional") {
        clearPendingInterrupt(conversationId, resolvedRequestId);
      }
    },
    [acknowledgeLocalInterruptResolution, clearPendingInterrupt],
  );

  useEffect(() => {
    if (!lastResolvedInterrupt) {
      return;
    }
    const observedAt = Date.parse(lastResolvedInterrupt.observedAt);
    if (Number.isFinite(observedAt) && observedAt < mountedAtRef.current) {
      return;
    }
    const key = buildResolvedInterruptKey(lastResolvedInterrupt);
    if (!key || handledResolvedInterruptKeysRef.current.has(key)) {
      return;
    }
    handledResolvedInterruptKeysRef.current.add(key);
    if (locallyAcknowledgedResolvedInterruptKeysRef.current.has(key)) {
      locallyAcknowledgedResolvedInterruptKeysRef.current.delete(key);
      return;
    }
    const feedback = buildResolvedInterruptFeedback(lastResolvedInterrupt);
    toast.success(feedback.title, feedback.message);
  }, [
    buildResolvedInterruptFeedback,
    buildResolvedInterruptKey,
    lastResolvedInterrupt,
  ]);

  useEffect(() => {
    if (!pendingInterrupt || pendingInterrupt.type !== "question") {
      setQuestionAnswers([]);
      return;
    }
    setQuestionAnswers((current) =>
      Array.from(
        { length: pendingQuestionCount },
        (_, index) => current[index] ?? "",
      ),
    );
  }, [
    pendingInterrupt?.requestId,
    pendingInterrupt?.type,
    pendingQuestionCount,
  ]);

  useEffect(() => {
    if (!pendingInterrupt) {
      setStructuredResponseInput("");
      return;
    }
    if (pendingInterrupt.type === "permissions") {
      try {
        setStructuredResponseInput(
          JSON.stringify(pendingInterrupt.details.permissions ?? {}, null, 2),
        );
      } catch {
        setStructuredResponseInput("{}");
      }
      return;
    }
    if (pendingInterrupt.type === "elicitation") {
      setStructuredResponseInput("");
      return;
    }
    setStructuredResponseInput("");
  }, [pendingInterrupt?.requestId, pendingInterrupt?.type]);

  const parseStructuredResponseInput = useCallback(
    ({
      rawValue,
      emptyMessage,
      invalidMessage,
    }: {
      rawValue: string;
      emptyMessage: string;
      invalidMessage: string;
    }) => {
      const trimmed = rawValue.trim();
      if (!trimmed) {
        toast.error("Invalid response", emptyMessage);
        return null;
      }
      try {
        return JSON.parse(trimmed);
      } catch {
        toast.error("Invalid response", invalidMessage);
        return null;
      }
    },
    [],
  );

  const handlePermissionReply = useCallback(
    (reply: "once" | "always" | "reject") => {
      if (
        !activeAgentId ||
        !conversationId ||
        !pendingInterrupt ||
        pendingInterrupt.type !== "permission"
      ) {
        return;
      }
      if (!onPermissionReplyOverride && !agentSource) {
        return;
      }
      const replyAgentSource = agentSource;
      const requestId = pendingInterrupt.requestId;
      runInterruptAction(
        `permission:${reply}`,
        async () => {
          let actionResult: InterruptActionResult = {
            mode: reply === "reject" ? "transactional" : "ack-fast",
            resolvedRequestId: requestId,
          };
          if (onPermissionReplyOverride) {
            actionResult = await onPermissionReplyOverride({
              requestId,
              reply,
            });
          } else if (replyAgentSource) {
            await replyPermissionInterrupt({
              source: replyAgentSource,
              agentId: activeAgentId,
              requestId,
              reply,
              ...(normalizedWorkingDirectory
                ? { workingDirectory: normalizedWorkingDirectory }
                : {}),
            });
            actionResult = {
              mode: reply === "reject" ? "transactional" : "ack-fast",
              resolvedRequestId: requestId,
            };
          } else {
            return;
          }
          finalizeInterruptAction({
            actionResult,
            conversationId,
            requestId,
            interruptType: "permission",
            resolution: reply === "reject" ? "rejected" : "replied",
          });
        },
        permissionReplySuccessMessage ??
          "Permission reply delivered to upstream.",
        {
          conversationId,
          requestId,
        },
      ).catch(() => undefined);
    },
    [
      activeAgentId,
      agentSource,
      conversationId,
      finalizeInterruptAction,
      pendingInterrupt,
      runInterruptAction,
      normalizedWorkingDirectory,
      onPermissionReplyOverride,
      permissionReplySuccessMessage,
    ],
  );

  const handleQuestionAnswerChange = useCallback(
    (index: number, value: string) => {
      setQuestionAnswers((current) => {
        const next = [...current];
        next[index] = value;
        return next;
      });
    },
    [],
  );

  const handleQuestionOptionPick = useCallback(
    (index: number, value: string) => {
      setQuestionAnswers((current) => {
        const next = [...current];
        next[index] = value;
        return next;
      });
    },
    [],
  );

  const handleQuestionReply = useCallback(() => {
    if (
      !activeAgentId ||
      !agentSource ||
      !conversationId ||
      !pendingInterrupt ||
      pendingInterrupt.type !== "question"
    ) {
      return;
    }
    const questions = pendingInterrupt.details.questions ?? [];
    const normalizedAnswers = questions.map((_, index) => {
      const answer = questionAnswers[index]?.trim() ?? "";
      return answer ? [answer] : [];
    });
    if (normalizedAnswers.some((group) => group.length === 0)) {
      toast.error("Missing answer", "Please answer all questions first.");
      return;
    }
    const requestId = pendingInterrupt.requestId;
    runInterruptAction(
      "question:reply",
      async () => {
        await replyQuestionInterrupt({
          source: agentSource,
          agentId: activeAgentId,
          requestId,
          answers: normalizedAnswers,
          ...(normalizedWorkingDirectory
            ? { workingDirectory: normalizedWorkingDirectory }
            : {}),
        });
        finalizeInterruptAction({
          actionResult: {
            mode: "ack-fast",
            resolvedRequestId: requestId,
          },
          conversationId,
          requestId,
          interruptType: "question",
          resolution: "replied",
        });
      },
      "Question answers delivered to upstream.",
      {
        conversationId,
        requestId,
      },
    ).catch(() => undefined);
  }, [
    activeAgentId,
    agentSource,
    conversationId,
    finalizeInterruptAction,
    pendingInterrupt,
    questionAnswers,
    runInterruptAction,
    normalizedWorkingDirectory,
  ]);

  const handleQuestionReject = useCallback(() => {
    if (
      !activeAgentId ||
      !agentSource ||
      !conversationId ||
      !pendingInterrupt ||
      pendingInterrupt.type !== "question"
    ) {
      return;
    }
    const requestId = pendingInterrupt.requestId;
    runInterruptAction(
      "question:reject",
      async () => {
        await rejectQuestionInterrupt({
          source: agentSource,
          agentId: activeAgentId,
          requestId,
          ...(normalizedWorkingDirectory
            ? { workingDirectory: normalizedWorkingDirectory }
            : {}),
        });
        finalizeInterruptAction({
          actionResult: {
            mode: "transactional",
            resolvedRequestId: requestId,
          },
          conversationId,
          requestId,
          interruptType: "question",
          resolution: "rejected",
        });
      },
      "Question request rejected.",
      {
        conversationId,
        requestId,
      },
    ).catch(() => undefined);
  }, [
    activeAgentId,
    agentSource,
    conversationId,
    finalizeInterruptAction,
    pendingInterrupt,
    runInterruptAction,
    normalizedWorkingDirectory,
  ]);

  const handleStructuredResponseChange = useCallback((value: string) => {
    setStructuredResponseInput(value);
  }, []);

  const handlePermissionsReply = useCallback(
    (scope: "turn" | "session") => {
      if (
        !activeAgentId ||
        !agentSource ||
        !conversationId ||
        !pendingInterrupt ||
        pendingInterrupt.type !== "permissions"
      ) {
        return;
      }
      const permissions = parseStructuredResponseInput({
        rawValue: structuredResponseInput,
        emptyMessage: "Provide a JSON permissions subset first.",
        invalidMessage: "Permissions subset must be valid JSON.",
      });
      if (
        !permissions ||
        typeof permissions !== "object" ||
        Array.isArray(permissions)
      ) {
        toast.error(
          "Invalid response",
          "Permissions subset must be a JSON object.",
        );
        return;
      }
      const requestId = pendingInterrupt.requestId;
      runInterruptAction(
        `permissions:${scope}`,
        async () => {
          await replyPermissionsInterrupt({
            source: agentSource,
            agentId: activeAgentId,
            requestId,
            permissions,
            scope,
            ...(normalizedWorkingDirectory
              ? { workingDirectory: normalizedWorkingDirectory }
              : {}),
          });
          finalizeInterruptAction({
            actionResult: {
              mode: "ack-fast",
              resolvedRequestId: requestId,
            },
            conversationId,
            requestId,
            interruptType: "permissions",
            resolution: "replied",
          });
        },
        `Permissions reply delivered to upstream (${scope}).`,
        {
          conversationId,
          requestId,
        },
      ).catch(() => undefined);
    },
    [
      activeAgentId,
      agentSource,
      conversationId,
      finalizeInterruptAction,
      parseStructuredResponseInput,
      pendingInterrupt,
      runInterruptAction,
      normalizedWorkingDirectory,
      structuredResponseInput,
    ],
  );

  const handleElicitationReply = useCallback(
    (action: "accept" | "decline" | "cancel") => {
      if (
        !activeAgentId ||
        !agentSource ||
        !conversationId ||
        !pendingInterrupt ||
        pendingInterrupt.type !== "elicitation"
      ) {
        return;
      }
      const content =
        action === "accept"
          ? parseStructuredResponseInput({
              rawValue: structuredResponseInput,
              emptyMessage: "Provide a JSON elicitation response first.",
              invalidMessage: "Elicitation response must be valid JSON.",
            })
          : undefined;
      if (action === "accept" && content === null) {
        return;
      }
      const requestId = pendingInterrupt.requestId;
      runInterruptAction(
        `elicitation:${action}`,
        async () => {
          await replyElicitationInterrupt({
            source: agentSource,
            agentId: activeAgentId,
            requestId,
            action,
            ...(action === "accept" ? { content } : {}),
            ...(normalizedWorkingDirectory
              ? { workingDirectory: normalizedWorkingDirectory }
              : {}),
          });
          finalizeInterruptAction({
            actionResult: {
              mode: "transactional",
              resolvedRequestId: requestId,
            },
            conversationId,
            requestId,
            interruptType: "elicitation",
            resolution: action === "accept" ? "replied" : "rejected",
          });
        },
        action === "accept"
          ? "Elicitation response delivered to upstream."
          : "Elicitation request closed.",
        {
          conversationId,
          requestId,
        },
      ).catch(() => undefined);
    },
    [
      activeAgentId,
      agentSource,
      conversationId,
      finalizeInterruptAction,
      parseStructuredResponseInput,
      pendingInterrupt,
      runInterruptAction,
      normalizedWorkingDirectory,
      structuredResponseInput,
    ],
  );

  return {
    interruptAction,
    questionAnswers,
    structuredResponseInput,
    handlePermissionReply,
    handlePermissionsReply,
    handleQuestionAnswerChange,
    handleQuestionOptionPick,
    handleQuestionReply,
    handleQuestionReject,
    handleStructuredResponseChange,
    handleElicitationReply,
  };
}
