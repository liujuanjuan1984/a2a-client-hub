import { useCallback, useEffect, useRef } from "react";

import { type ResolvedRuntimeInterrupt } from "@/lib/api/chat-utils";
import { toast } from "@/lib/toast";

export function useA2AResolutionWatcher(
  lastResolvedInterrupt: ResolvedRuntimeInterrupt | null,
) {
  const handledResolvedInterruptKeysRef = useRef<Set<string>>(new Set());
  const locallyAcknowledgedResolvedInterruptKeysRef = useRef<Set<string>>(
    new Set(),
  );

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

  useEffect(() => {
    if (!lastResolvedInterrupt) return;

    const key = buildResolvedInterruptKey(lastResolvedInterrupt);
    if (!key || handledResolvedInterruptKeysRef.current.has(key)) return;

    handledResolvedInterruptKeysRef.current.add(key);

    if (locallyAcknowledgedResolvedInterruptKeysRef.current.has(key)) {
      locallyAcknowledgedResolvedInterruptKeysRef.current.delete(key);
      return;
    }

    const { title, message } =
      lastResolvedInterrupt.type === "permission"
        ? {
            title: "Interrupt resolved",
            message: "Authorization request was handled.",
          }
        : lastResolvedInterrupt.resolution === "rejected"
          ? {
              title: "Interrupt resolved",
              message:
                "Question request was rejected and the interrupt is closed.",
            }
          : {
              title: "Interrupt resolved",
              message: "Question answer received. Agent resumed.",
            };

    toast.success(title, message);
  }, [buildResolvedInterruptKey, lastResolvedInterrupt]);

  return { acknowledgeLocalInterruptResolution };
}
