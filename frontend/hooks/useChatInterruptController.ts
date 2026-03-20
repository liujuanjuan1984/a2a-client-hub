import { useCallback, useEffect, useRef, useState } from "react";

import {
  A2AExtensionCallError,
  rejectQuestionInterrupt,
  replyPermissionInterrupt,
  replyQuestionInterrupt,
} from "@/lib/api/a2aExtensions";
import { type PendingRuntimeInterrupt } from "@/lib/api/chat-utils";
import { ApiRequestError } from "@/lib/api/client";
import { type ResolvedRuntimeInterruptRecord } from "@/lib/chat-utils";
import { pickOpencodeDirectoryMetadata } from "@/lib/opencodeMetadata";
import { toast } from "@/lib/toast";
import type { AgentSource } from "@/store/agents";

type ResolvedInterruptKeyInput = {
  requestId: string;
  type: "permission" | "question";
  resolution: "replied" | "rejected";
};

type UseChatInterruptControllerParams = {
  activeAgentId?: string | null;
  agentSource?: AgentSource | null;
  conversationId?: string;
  pendingInterrupt: PendingRuntimeInterrupt | null;
  lastResolvedInterrupt: ResolvedRuntimeInterruptRecord | null;
  pendingQuestionCount: number;
  sessionMetadata?: Record<string, unknown>;
  clearPendingInterrupt: (conversationId: string, requestId?: string) => void;
};

export function useChatInterruptController({
  activeAgentId,
  agentSource,
  conversationId,
  pendingInterrupt,
  lastResolvedInterrupt,
  pendingQuestionCount,
  sessionMetadata,
  clearPendingInterrupt,
}: UseChatInterruptControllerParams) {
  const [interruptAction, setInterruptAction] = useState<string | null>(null);
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);
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
      interruptType: "permission" | "question",
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
        return {
          title: "Interrupt resolved",
          message: "Authorization request was handled.",
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
    ) => {
      setInterruptAction(actionKey);
      try {
        await executor();
        toast.success("Action submitted", successMessage);
      } catch (error) {
        toast.error(
          "Interrupt callback failed",
          buildInterruptErrorMessage(error),
        );
      } finally {
        setInterruptAction(null);
      }
    },
    [buildInterruptErrorMessage],
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

  const handlePermissionReply = useCallback(
    (reply: "once" | "always" | "reject") => {
      if (
        !activeAgentId ||
        !agentSource ||
        !conversationId ||
        !pendingInterrupt ||
        pendingInterrupt.type !== "permission"
      ) {
        return;
      }
      const requestId = pendingInterrupt.requestId;
      runInterruptAction(
        `permission:${reply}`,
        async () => {
          await replyPermissionInterrupt({
            source: agentSource,
            agentId: activeAgentId,
            requestId,
            reply,
            metadata: pickOpencodeDirectoryMetadata(sessionMetadata),
          });
          acknowledgeLocalInterruptResolution(
            requestId,
            "permission",
            "replied",
          );
          clearPendingInterrupt(conversationId, requestId);
        },
        "Permission reply delivered to upstream.",
      ).catch(() => undefined);
    },
    [
      activeAgentId,
      agentSource,
      acknowledgeLocalInterruptResolution,
      clearPendingInterrupt,
      conversationId,
      pendingInterrupt,
      runInterruptAction,
      sessionMetadata,
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
          metadata: pickOpencodeDirectoryMetadata(sessionMetadata),
        });
        acknowledgeLocalInterruptResolution(requestId, "question", "replied");
        clearPendingInterrupt(conversationId, requestId);
      },
      "Question answers delivered to upstream.",
    ).catch(() => undefined);
  }, [
    activeAgentId,
    agentSource,
    acknowledgeLocalInterruptResolution,
    clearPendingInterrupt,
    conversationId,
    pendingInterrupt,
    questionAnswers,
    runInterruptAction,
    sessionMetadata,
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
          metadata: pickOpencodeDirectoryMetadata(sessionMetadata),
        });
        acknowledgeLocalInterruptResolution(requestId, "question", "rejected");
        clearPendingInterrupt(conversationId, requestId);
      },
      "Question request rejected.",
    ).catch(() => undefined);
  }, [
    activeAgentId,
    agentSource,
    acknowledgeLocalInterruptResolution,
    clearPendingInterrupt,
    conversationId,
    pendingInterrupt,
    runInterruptAction,
    sessionMetadata,
  ]);

  return {
    interruptAction,
    questionAnswers,
    handlePermissionReply,
    handleQuestionAnswerChange,
    handleQuestionOptionPick,
    handleQuestionReply,
    handleQuestionReject,
  };
}
