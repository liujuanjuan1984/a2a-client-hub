import { useCallback, useEffect, useRef, useState } from "react";

import {
  A2AExtensionCallError,
  rejectQuestionInterrupt,
  replyPermissionInterrupt,
  replyQuestionInterrupt,
} from "@/lib/api/a2aExtensions";
import {
  type PendingRuntimeInterrupt,
  type ResolvedRuntimeInterrupt,
  type InterruptQuestion,
} from "@/lib/api/chat-utils";
import { ApiRequestError } from "@/lib/api/client";
import { type ResolvedRuntimeInterruptRecord } from "@/lib/chat-utils";
import { toast } from "@/lib/toast";
import { type AgentConfig } from "@/store/agents";
import { useChatStore } from "@/store/chat";

export function useA2AIntegration(
  conversationId: string | undefined,
  activeAgentId: string | null,
  agent: AgentConfig | undefined,
  pendingInterrupt: PendingRuntimeInterrupt | null | undefined,
  lastResolvedInterrupt: ResolvedRuntimeInterruptRecord | null | undefined,
  mountedAtRef: React.MutableRefObject<number>,
) {
  const [interruptAction, setInterruptAction] = useState<string | null>(null);
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);
  const handledResolvedInterruptKeysRef = useRef<Set<string>>(new Set());
  const locallyAcknowledgedResolvedInterruptKeysRef = useRef<Set<string>>(
    new Set(),
  );
  const clearPendingInterrupt = useChatStore(
    (state) => state.clearPendingInterrupt,
  );

  const buildInterruptErrorMessage = useCallback((error: unknown) => {
    if (error instanceof ApiRequestError) {
      const codeSuffix = error.errorCode ? ` [${error.errorCode}]` : "";
      const upstreamMessage =
        error.upstreamError &&
        typeof error.upstreamError === "object" &&
        typeof (error.upstreamError as any).message === "string"
          ? (error.upstreamError as any).message
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
    (interrupt: ResolvedRuntimeInterrupt | null) =>
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
          phase: "resolved",
          resolution,
        }),
      );
    },
    [buildResolvedInterruptKey],
  );

  const buildResolvedInterruptFeedback = useCallback(
    (interrupt: ResolvedRuntimeInterrupt) => {
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
    mountedAtRef,
  ]);

  const pendingQuestionCount =
    pendingInterrupt?.type === "question"
      ? (pendingInterrupt.details?.questions?.length ?? 0)
      : 0;

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

  const handlePermissionReply = useCallback(
    (reply: "once" | "always" | "reject") => {
      if (!activeAgentId || !conversationId || !pendingInterrupt || !agent) {
        return;
      }
      if (pendingInterrupt.type !== "permission") {
        return;
      }
      const requestId = pendingInterrupt.requestId;
      runInterruptAction(
        `permission:${reply}`,
        async () => {
          await replyPermissionInterrupt({
            source: agent.source,
            agentId: activeAgentId,
            requestId,
            reply,
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
      agent,
      acknowledgeLocalInterruptResolution,
      clearPendingInterrupt,
      conversationId,
      pendingInterrupt,
      runInterruptAction,
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
    if (!activeAgentId || !conversationId || !pendingInterrupt || !agent) {
      return;
    }
    if (pendingInterrupt.type !== "question") {
      return;
    }
    const questions = pendingInterrupt.details?.questions ?? [];
    const normalizedAnswers = questions.map(
      (_: InterruptQuestion, index: number) => {
        const answer = questionAnswers[index]?.trim() ?? "";
        return answer ? [answer] : [];
      },
    );
    if (normalizedAnswers.some((group: string[]) => group.length === 0)) {
      toast.error("Missing answer", "Please answer all questions first.");
      return;
    }
    const requestId = pendingInterrupt.requestId;
    runInterruptAction(
      "question:reply",
      async () => {
        await replyQuestionInterrupt({
          source: agent.source,
          agentId: activeAgentId,
          requestId,
          answers: normalizedAnswers,
        });
        acknowledgeLocalInterruptResolution(requestId, "question", "replied");
        clearPendingInterrupt(conversationId, requestId);
      },
      "Question answers delivered to upstream.",
    ).catch(() => undefined);
  }, [
    activeAgentId,
    agent,
    acknowledgeLocalInterruptResolution,
    clearPendingInterrupt,
    conversationId,
    pendingInterrupt,
    questionAnswers,
    runInterruptAction,
  ]);

  const handleQuestionReject = useCallback(() => {
    if (!activeAgentId || !conversationId || !pendingInterrupt || !agent) {
      return;
    }
    if (pendingInterrupt.type !== "question") {
      return;
    }
    const requestId = pendingInterrupt.requestId;
    runInterruptAction(
      "question:reject",
      async () => {
        await rejectQuestionInterrupt({
          source: agent.source,
          agentId: activeAgentId,
          requestId,
        });
        acknowledgeLocalInterruptResolution(requestId, "question", "rejected");
        clearPendingInterrupt(conversationId, requestId);
      },
      "Question request rejected.",
    ).catch(() => undefined);
  }, [
    activeAgentId,
    agent,
    acknowledgeLocalInterruptResolution,
    clearPendingInterrupt,
    conversationId,
    pendingInterrupt,
    runInterruptAction,
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
