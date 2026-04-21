import { useCallback, useEffect, useRef } from "react";

import { type InterruptActionResult } from "@/hooks/useChatInterruptController";
import {
  type ContinuationConvergenceEvent,
  useContinuationConvergence,
} from "@/hooks/useContinuationConvergence";
import { type PendingRuntimeInterrupt } from "@/lib/api/chat-utils";
import {
  getHubAssistantProfile,
  recoverHubAssistantPermissionInterrupts,
  replyHubAssistantPermissionInterrupt,
  runHubAssistant,
  toPendingRuntimePermissionInterrupt,
} from "@/lib/api/hubAssistant";
import { listSessionMessagesPage } from "@/lib/api/sessions";
import {
  buildPendingInterruptState,
  createAgentSession,
  type ResolvedRuntimeInterruptRecord,
} from "@/lib/chat-utils";
import {
  addConversationMessage,
  mergeConversationMessages,
  removeConversationMessage,
  updateConversationMessage,
} from "@/lib/chatHistoryCache";
import { generateUuid } from "@/lib/id";
import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/store/chat";

const INTERRUPT_RECOVERY_THROTTLE_MS = 5_000;
const HUB_ASSISTANT_CONTINUATION_POLL_INTERVAL_MS = 800;
const HUB_ASSISTANT_CONTINUATION_POLL_MAX_INTERVAL_MS = 5_000;
const HUB_ASSISTANT_IDLE_REFRESH_INTERVAL_MS = 5_000;

type EnsureSessionFn = (conversationId: string, agentId: string) => void;
type ReplaceRecoveredInterruptsFn = (
  conversationId: string,
  items: PendingRuntimeInterrupt[],
  options?: { sessionId?: string; replaceAllForConversation?: boolean },
) => void;

export function useChatScreenHubAssistantController({
  activeAgentId,
  conversationId,
  isHubAssistantAgent,
  streamState,
  lastAgentMessageId,
  ensureSession,
  replaceRecoveredInterrupts,
}: {
  activeAgentId: string | null | undefined;
  conversationId: string | undefined;
  isHubAssistantAgent: boolean;
  streamState: string | null | undefined;
  lastAgentMessageId: string | null | undefined;
  ensureSession: EnsureSessionFn;
  replaceRecoveredInterrupts: ReplaceRecoveredInterruptsFn;
}) {
  const lastInterruptRecoveryRef = useRef<{
    key: string;
    triggeredAt: number;
  } | null>(null);

  const applyHubAssistantSessionUpdate = useCallback(
    (
      nextConversationId: string,
      nextAgentId: string,
      updater: (
        current: ReturnType<typeof createAgentSession>,
      ) => ReturnType<typeof createAgentSession>,
    ) => {
      useChatStore.setState((state) => {
        const current =
          state.sessions[nextConversationId] ?? createAgentSession(nextAgentId);
        return {
          sessions: {
            ...state.sessions,
            [nextConversationId]: updater(current),
          },
        };
      });
    },
    [],
  );

  const buildResolvedInterruptRecord = useCallback(
    (
      requestId: string,
      resolution: "replied" | "rejected",
    ): ResolvedRuntimeInterruptRecord => ({
      requestId,
      type: "permission",
      phase: "resolved",
      resolution,
      observedAt: new Date().toISOString(),
    }),
    [],
  );

  const recoverPendingInterrupts = useCallback(
    async ({ nextConversationId }: { nextConversationId: string }) => {
      const resolvedSessionId = nextConversationId.trim();
      if (!resolvedSessionId) {
        return;
      }

      const recoveryKey = `${resolvedSessionId}:${resolvedSessionId}`;
      const lastRecovery = lastInterruptRecoveryRef.current;
      if (
        lastRecovery &&
        lastRecovery.key === recoveryKey &&
        Date.now() - lastRecovery.triggeredAt < INTERRUPT_RECOVERY_THROTTLE_MS
      ) {
        return;
      }
      lastInterruptRecoveryRef.current = {
        key: recoveryKey,
        triggeredAt: Date.now(),
      };

      try {
        const result = await recoverHubAssistantPermissionInterrupts({
          conversationId: resolvedSessionId,
        });
        replaceRecoveredInterrupts(nextConversationId, result.items, {
          sessionId: resolvedSessionId,
          replaceAllForConversation: true,
        });
      } catch (error) {
        console.warn("[Chat] Hub Assistant interrupt recovery failed", {
          conversationId: nextConversationId,
          error:
            error instanceof Error
              ? error.message
              : "hub_assistant_interrupt_recovery_failed",
        });
      }
    },
    [replaceRecoveredInterrupts],
  );

  const sendHubAssistantMessage = useCallback(
    async (
      nextConversationId: string,
      nextAgentId: string,
      content: string,
    ) => {
      const trimmedContent = content.trim();
      if (!trimmedContent) {
        return;
      }

      const userMessageId = generateUuid();
      const agentMessageId = generateUuid();
      const createdAt = new Date().toISOString();

      ensureSession(nextConversationId, nextAgentId);
      applyHubAssistantSessionUpdate(
        nextConversationId,
        nextAgentId,
        (current) => ({
          ...current,
          agentId: nextAgentId,
          lastActiveAt: createdAt,
          streamState: "streaming",
          lastStreamError: null,
          lastUserMessageId: userMessageId,
          lastAgentMessageId: agentMessageId,
          lastResolvedInterrupt: null,
          ...buildPendingInterruptState([]),
        }),
      );

      addConversationMessage(nextConversationId, {
        id: userMessageId,
        role: "user",
        content: trimmedContent,
        createdAt,
        status: "done",
      });
      addConversationMessage(nextConversationId, {
        id: agentMessageId,
        role: "agent",
        content: "",
        createdAt,
        status: "streaming",
        blocks: [],
      });

      try {
        const result = await runHubAssistant({
          conversationId: nextConversationId,
          message: trimmedContent,
          userMessageId,
          agentMessageId,
        });
        const nextInterrupt = result.interrupt
          ? toPendingRuntimePermissionInterrupt(result.interrupt)
          : null;

        updateConversationMessage(nextConversationId, agentMessageId, {
          content: result.answer ?? "",
          status: result.status === "interrupted" ? "interrupted" : "done",
        });
        applyHubAssistantSessionUpdate(
          nextConversationId,
          nextAgentId,
          (current) => ({
            ...current,
            agentId: nextAgentId,
            lastActiveAt: new Date().toISOString(),
            streamState: "idle",
            lastStreamError: null,
            ...buildPendingInterruptState(nextInterrupt ? [nextInterrupt] : []),
          }),
        );
      } catch (error) {
        updateConversationMessage(nextConversationId, agentMessageId, {
          content:
            error instanceof Error
              ? error.message
              : "Hub Assistant request failed.",
          status: "error",
        });
        applyHubAssistantSessionUpdate(
          nextConversationId,
          nextAgentId,
          (current) => ({
            ...current,
            agentId: nextAgentId,
            lastActiveAt: new Date().toISOString(),
            streamState: "error",
            lastStreamError:
              error instanceof Error
                ? error.message
                : "Hub Assistant request failed.",
            ...buildPendingInterruptState([]),
          }),
        );
        throw error;
      }
    },
    [applyHubAssistantSessionUpdate, ensureSession],
  );

  const handlePermissionReply = useCallback(
    async ({
      requestId,
      reply,
    }: {
      requestId: string;
      reply: "once" | "always" | "reject";
    }): Promise<InterruptActionResult> => {
      if (!conversationId || !activeAgentId) {
        return {
          mode: "transactional",
          resolvedRequestId: requestId,
        };
      }

      const nextAgentMessageId = generateUuid();
      const createdAt = new Date().toISOString();
      applyHubAssistantSessionUpdate(
        conversationId,
        activeAgentId,
        (current) => ({
          ...current,
          agentId: activeAgentId,
          lastActiveAt: createdAt,
          streamState: "streaming",
          lastStreamError: null,
          lastAgentMessageId: nextAgentMessageId,
        }),
      );
      addConversationMessage(conversationId, {
        id: nextAgentMessageId,
        role: "agent",
        content: "",
        createdAt,
        status: "streaming",
        blocks: [],
      });

      try {
        const result = await replyHubAssistantPermissionInterrupt({
          requestId,
          reply,
          agentMessageId: nextAgentMessageId,
        });

        const resolution = reply === "reject" ? "rejected" : "replied";
        const nextInterrupt = result.interrupt
          ? toPendingRuntimePermissionInterrupt(result.interrupt)
          : null;

        if (result.status === "accepted") {
          applyHubAssistantSessionUpdate(
            conversationId,
            activeAgentId,
            (current) => ({
              ...current,
              agentId: activeAgentId,
              lastActiveAt: new Date().toISOString(),
              streamState: "continuing",
              lastStreamError: null,
              lastAgentMessageId:
                result.continuation?.agentMessageId ?? nextAgentMessageId,
              lastResolvedInterrupt: buildResolvedInterruptRecord(
                requestId,
                resolution,
              ),
              ...buildPendingInterruptState([]),
            }),
          );
          return {
            mode: "ack-fast",
            resolvedRequestId: requestId,
          };
        }

        updateConversationMessage(conversationId, nextAgentMessageId, {
          content: result.answer ?? "",
          status: result.status === "interrupted" ? "interrupted" : "done",
        });
        applyHubAssistantSessionUpdate(
          conversationId,
          activeAgentId,
          (current) => ({
            ...current,
            agentId: activeAgentId,
            lastActiveAt: new Date().toISOString(),
            streamState: "idle",
            lastStreamError: null,
            lastResolvedInterrupt: buildResolvedInterruptRecord(
              requestId,
              resolution,
            ),
            ...buildPendingInterruptState(nextInterrupt ? [nextInterrupt] : []),
          }),
        );
        return {
          mode: "transactional",
          resolvedRequestId: requestId,
        };
      } catch (error) {
        removeConversationMessage(conversationId, nextAgentMessageId);
        applyHubAssistantSessionUpdate(
          conversationId,
          activeAgentId,
          (current) => ({
            ...current,
            agentId: activeAgentId,
            lastActiveAt: new Date().toISOString(),
            streamState: "idle",
            lastStreamError: null,
          }),
        );
        throw error;
      }
    },
    [
      activeAgentId,
      applyHubAssistantSessionUpdate,
      buildResolvedInterruptRecord,
      conversationId,
    ],
  );

  useEffect(() => {
    if (!conversationId || !activeAgentId || !isHubAssistantAgent) {
      return;
    }
    recoverPendingInterrupts({
      nextConversationId: conversationId,
    });
  }, [
    activeAgentId,
    conversationId,
    isHubAssistantAgent,
    recoverPendingInterrupts,
  ]);

  useEffect(() => {
    if (
      !conversationId ||
      !activeAgentId ||
      !isHubAssistantAgent ||
      streamState !== "recoverable"
    ) {
      return;
    }
    recoverPendingInterrupts({
      nextConversationId: conversationId,
    });
  }, [
    activeAgentId,
    conversationId,
    isHubAssistantAgent,
    recoverPendingInterrupts,
    streamState,
  ]);

  const loadContinuationMessages = useCallback(async () => {
    if (!conversationId) {
      return [];
    }
    const page = await listSessionMessagesPage(conversationId, {
      before: null,
      limit: 8,
    });
    return mapSessionMessagesToChatMessages(
      Array.isArray(page?.items) ? page.items : [],
      {
        keepEmptyMessages: true,
      },
    );
  }, [conversationId]);

  const handleContinuationConverged = useCallback(
    async (event: ContinuationConvergenceEvent) => {
      if (!conversationId || !activeAgentId) {
        return;
      }
      if (event.status === "interrupted") {
        await recoverPendingInterrupts({
          nextConversationId: conversationId,
        });
      }
      applyHubAssistantSessionUpdate(
        conversationId,
        activeAgentId,
        (current) => ({
          ...current,
          agentId: activeAgentId,
          lastActiveAt: new Date().toISOString(),
          streamState: event.status === "error" ? "error" : "idle",
          lastStreamError:
            event.status === "error"
              ? event.message.content.trim() ||
                "Hub Assistant continuation failed."
              : null,
        }),
      );
    },
    [
      activeAgentId,
      applyHubAssistantSessionUpdate,
      conversationId,
      recoverPendingInterrupts,
    ],
  );

  const handleContinuationRefreshError = useCallback(
    (error: unknown) => {
      console.warn("[Chat] Hub Assistant continuation refresh failed", {
        conversationId,
        agentId: activeAgentId,
        agentMessageId: lastAgentMessageId,
        error:
          error instanceof Error
            ? error.message
            : "hub_assistant_continuation_refresh_failed",
      });
    },
    [activeAgentId, conversationId, lastAgentMessageId],
  );

  const handleContinuationMessagesLoaded = useCallback(
    (messages: Awaited<ReturnType<typeof loadContinuationMessages>>) => {
      if (conversationId) {
        mergeConversationMessages(conversationId, messages);
      }
    },
    [conversationId],
  );

  useContinuationConvergence({
    enabled: Boolean(
      conversationId &&
      activeAgentId &&
      isHubAssistantAgent &&
      streamState === "continuing" &&
      lastAgentMessageId,
    ),
    source: "persisted-history",
    monitorKey:
      conversationId && lastAgentMessageId
        ? `${conversationId}:${lastAgentMessageId}`
        : null,
    targetMessageId: lastAgentMessageId ?? null,
    loadMessages: loadContinuationMessages,
    onMessagesLoaded: handleContinuationMessagesLoaded,
    onConverged: handleContinuationConverged,
    onRefreshError: handleContinuationRefreshError,
    initialPollDelayMs: HUB_ASSISTANT_CONTINUATION_POLL_INTERVAL_MS,
    maxPollDelayMs: HUB_ASSISTANT_CONTINUATION_POLL_MAX_INTERVAL_MS,
  });

  useEffect(() => {
    if (
      !conversationId ||
      !activeAgentId ||
      !isHubAssistantAgent ||
      streamState === "streaming" ||
      streamState === "continuing"
    ) {
      return;
    }

    let cancelled = false;
    let refreshTimeout: ReturnType<typeof setTimeout> | null = null;

    const scheduleRefresh = () => {
      if (cancelled) {
        return;
      }
      refreshTimeout = setTimeout(() => {
        runRefresh().catch(() => undefined);
      }, HUB_ASSISTANT_IDLE_REFRESH_INTERVAL_MS);
    };

    const runRefresh = async () => {
      if (cancelled) {
        return;
      }
      try {
        const page = await listSessionMessagesPage(conversationId, {
          before: null,
          limit: 8,
        });
        const mappedMessages = mapSessionMessagesToChatMessages(
          Array.isArray(page?.items) ? page.items : [],
          {
            keepEmptyMessages: true,
          },
        );
        mergeConversationMessages(conversationId, mappedMessages);
        const latestAgentMessage = [...mappedMessages]
          .reverse()
          .find((message) => message.role === "agent");
        if (latestAgentMessage?.status === "interrupted") {
          await recoverPendingInterrupts({
            nextConversationId: conversationId,
          });
        }
      } catch (error) {
        console.warn("[Chat] Hub Assistant idle refresh failed", {
          conversationId,
          agentId: activeAgentId,
          error:
            error instanceof Error
              ? error.message
              : "hub_assistant_idle_refresh_failed",
        });
      } finally {
        scheduleRefresh();
      }
    };

    scheduleRefresh();

    return () => {
      cancelled = true;
      if (refreshTimeout) {
        clearTimeout(refreshTimeout);
      }
    };
  }, [
    activeAgentId,
    conversationId,
    isHubAssistantAgent,
    recoverPendingInterrupts,
    streamState,
  ]);

  const testConnection = useCallback(async () => {
    const profile = await getHubAssistantProfile();
    if (!profile.configured) {
      throw new Error("Hub Assistant is not configured.");
    }
    toast.success("Connection OK", `${profile.name} is ready.`);
  }, []);

  return {
    sendHubAssistantMessage,
    handleHubAssistantPermissionReply: handlePermissionReply,
    testHubAssistantConnection: testConnection,
  };
}
