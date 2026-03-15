import { useCallback } from "react";

import {
  rejectQuestionInterrupt,
  replyPermissionInterrupt,
  replyQuestionInterrupt,
} from "@/lib/api/a2aExtensions";
import {
  type PendingRuntimeInterrupt,
  type InterruptQuestion,
} from "@/lib/api/chat-utils";
import { ApiRequestError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { type AgentConfig } from "@/store/agents";
import { useChatStore } from "@/store/chat";

export function useA2AHandlers({
  conversationId,
  agent,
  pendingInterrupt,
  questionAnswers,
  setQuestionAnswers,
  setInterruptAction,
  acknowledgeLocalInterruptResolution,
}: {
  conversationId: string | undefined;
  agent: AgentConfig | undefined;
  pendingInterrupt: PendingRuntimeInterrupt | null;
  questionAnswers: string[];
  setQuestionAnswers: React.Dispatch<React.SetStateAction<string[]>>;
  setInterruptAction: (action: string | null) => void;
  acknowledgeLocalInterruptResolution: (
    requestId: string,
    interruptType: "permission" | "question",
    resolution: "replied" | "rejected",
  ) => void;
}) {
  const activeAgentId = agent?.id ?? null;
  const clearPendingInterrupt = useChatStore(
    (state) => state.clearPendingInterrupt,
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
        let message = "Interrupt callback failed.";
        if (error instanceof ApiRequestError) {
          const codeSuffix = error.errorCode ? ` [${error.errorCode}]` : "";
          const upstream = (error.upstreamError as any)?.message;
          message = upstream
            ? `${error.message}${codeSuffix}：${upstream}`
            : `${error.message}${codeSuffix}`;
        } else if (error instanceof Error) {
          message = error.message;
        }
        toast.error("Interrupt callback failed", message);
      } finally {
        setInterruptAction(null);
      }
    },
    [setInterruptAction],
  );

  const handlePermissionReply = useCallback(
    (reply: "once" | "always" | "reject") => {
      if (
        !activeAgentId ||
        !conversationId ||
        !pendingInterrupt ||
        !agent ||
        pendingInterrupt.type !== "permission"
      )
        return;
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
        "Permission reply delivered.",
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

  const handleQuestionReply = useCallback(() => {
    if (
      !activeAgentId ||
      !conversationId ||
      !pendingInterrupt ||
      !agent ||
      pendingInterrupt.type !== "question"
    )
      return;
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
      "Answers delivered.",
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
    if (
      !activeAgentId ||
      !conversationId ||
      !pendingInterrupt ||
      !agent ||
      pendingInterrupt.type !== "question"
    )
      return;
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
      "Rejected.",
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
    handlePermissionReply,
    handleQuestionReply,
    handleQuestionReject,
    handleQuestionAnswerChange: useCallback(
      (index: number, value: string) => {
        setQuestionAnswers((prev) => {
          const next = [...prev];
          next[index] = value;
          return next;
        });
      },
      [setQuestionAnswers],
    ),
    handleQuestionOptionPick: useCallback(
      (index: number, value: string) => {
        setQuestionAnswers((prev) => {
          const next = [...prev];
          next[index] = value;
          return next;
        });
      },
      [setQuestionAnswers],
    ),
  };
}
