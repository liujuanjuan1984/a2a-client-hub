import { useEffect, useRef } from "react";

import { type ChatMessage } from "@/lib/api/chat-utils";

type ContinuationConvergenceSource =
  | "persisted-history"
  | "runtime-status"
  | "stream";

type ContinuationConvergenceStatus = Exclude<
  NonNullable<ChatMessage["status"]>,
  "streaming"
>;

export type ContinuationConvergenceEvent = {
  source: ContinuationConvergenceSource;
  status: ContinuationConvergenceStatus;
  message: ChatMessage;
};

type UseContinuationConvergenceParams = {
  enabled: boolean;
  source: "persisted-history";
  monitorKey: string | null;
  targetMessageId: string | null;
  loadMessages: () => Promise<ChatMessage[]>;
  onMessagesLoaded?: (messages: ChatMessage[]) => void;
  onConverged: (event: ContinuationConvergenceEvent) => void | Promise<void>;
  onRefreshError?: (error: unknown) => void;
  initialPollDelayMs: number;
  maxPollDelayMs: number;
};

export const resolvePersistedHistoryContinuation = ({
  messages,
  targetMessageId,
}: {
  messages: ChatMessage[];
  targetMessageId: string;
}): ContinuationConvergenceEvent | null => {
  const currentAgentMessage = messages.find(
    (message) => message.id === targetMessageId && message.role === "agent",
  );
  if (
    !currentAgentMessage?.status ||
    currentAgentMessage.status === "streaming"
  ) {
    return null;
  }
  return {
    source: "persisted-history",
    status: currentAgentMessage.status,
    message: currentAgentMessage,
  };
};

export function useContinuationConvergence({
  enabled,
  source,
  monitorKey,
  targetMessageId,
  loadMessages,
  onMessagesLoaded,
  onConverged,
  onRefreshError,
  initialPollDelayMs,
  maxPollDelayMs,
}: UseContinuationConvergenceParams) {
  const monitorRef = useRef<{
    key: string;
    cancelled: boolean;
  } | null>(null);

  useEffect(() => {
    const resolvedTargetMessageId = targetMessageId?.trim() ?? "";
    const resolvedMonitorKey = monitorKey?.trim() ?? "";
    if (!enabled || !resolvedTargetMessageId || !resolvedMonitorKey) {
      return;
    }

    const nextMonitorKey = `${source}:${resolvedMonitorKey}`;
    const previousMonitor = monitorRef.current;
    if (previousMonitor?.key === nextMonitorKey && !previousMonitor.cancelled) {
      return;
    }
    if (previousMonitor) {
      previousMonitor.cancelled = true;
    }

    const monitor = {
      key: nextMonitorKey,
      cancelled: false,
    };
    monitorRef.current = monitor;

    const sleep = (ms: number) =>
      new Promise<void>((resolve) => {
        setTimeout(resolve, ms);
      });

    const runConvergence = async () => {
      let pollDelayMs = initialPollDelayMs;
      while (!monitor.cancelled) {
        try {
          const messages = await loadMessages();
          if (monitor.cancelled) {
            return;
          }
          onMessagesLoaded?.(messages);
          const event = resolvePersistedHistoryContinuation({
            messages,
            targetMessageId: resolvedTargetMessageId,
          });
          if (event) {
            await onConverged(event);
            return;
          }
        } catch (error) {
          if (!monitor.cancelled) {
            onRefreshError?.(error);
          }
        }
        await sleep(pollDelayMs);
        pollDelayMs = Math.min(maxPollDelayMs, Math.round(pollDelayMs * 1.5));
      }
    };

    const convergencePromise = runConvergence();
    convergencePromise.catch((error) => {
      if (!monitor.cancelled) {
        onRefreshError?.(error);
      }
    });

    return () => {
      monitor.cancelled = true;
      if (monitorRef.current === monitor) {
        monitorRef.current = null;
      }
    };
  }, [
    enabled,
    initialPollDelayMs,
    loadMessages,
    maxPollDelayMs,
    monitorKey,
    onConverged,
    onMessagesLoaded,
    onRefreshError,
    source,
    targetMessageId,
  ]);
}
