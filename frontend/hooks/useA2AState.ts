import { useEffect, useState } from "react";

import { type PendingRuntimeInterrupt } from "@/lib/api/chat-utils";

export function useA2AState(pendingInterrupt: PendingRuntimeInterrupt | null) {
  const [interruptAction, setInterruptAction] = useState<string | null>(null);
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);

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

  return {
    interruptAction,
    setInterruptAction,
    questionAnswers,
    setQuestionAnswers,
  };
}
