import { useCallback, useMemo } from "react";

import { type GenericCapabilityStatus } from "./useExtensionCapabilitiesQuery";

import { invokeAgent } from "@/lib/api/a2aAgents";
import {
  type PendingRuntimeInterrupt,
  type RuntimeStatusContract,
} from "@/lib/api/chat-utils";
import { invokeHubAgent } from "@/lib/api/hubA2aAgentsUser";
import { isHubAssistant } from "@/lib/api/hubAssistant";
import {
  appendSessionMessage,
  runSessionCommand,
  type SessionMessageItem,
} from "@/lib/api/sessions";
import { buildInvokePayload, type AgentSession } from "@/lib/chat-utils";
import { addConversationMessage } from "@/lib/chatHistoryCache";
import { generateUuid } from "@/lib/id";
import { parseComposerInput } from "@/lib/sessionCommand";
import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";
import { readSharedStreamIdentity } from "@/lib/sharedMetadata";
import { toast } from "@/lib/toast";
import { type AgentSource } from "@/store/agents";
import { useChatStore } from "@/store/chat";

type UseChatScreenSessionControllerParams = {
  session?: AgentSession;
  pendingInterrupt: PendingRuntimeInterrupt | null;
  sessionAppendStatus: GenericCapabilityStatus;
  sessionAppendRequiresStreamIdentity: boolean;
  sessionCommandStatus: GenericCapabilityStatus;
  runtimeStatusContract?: RuntimeStatusContract | null;
  sendHubAssistantMessage: (
    conversationId: string,
    agentId: string,
    content: string,
  ) => Promise<void>;
  sendMessage: (
    conversationId: string,
    agentId: string,
    content: string,
    agentSource: AgentSource,
    runtimeStatusContract?: RuntimeStatusContract | null,
  ) => Promise<void>;
};

export function useChatScreenSessionController({
  session,
  pendingInterrupt,
  sessionAppendStatus,
  sessionAppendRequiresStreamIdentity,
  sessionCommandStatus,
  runtimeStatusContract,
  sendHubAssistantMessage,
  sendMessage,
}: UseChatScreenSessionControllerParams) {
  const buildSkippedToastError = useCallback((message: string) => {
    const error = new Error(message);
    (error as Error & { skipToast?: boolean }).skipToast = true;
    return error;
  }, []);

  const addCanonicalSessionMessages = useCallback(
    (conversationId: string, items: SessionMessageItem[]) => {
      mapSessionMessagesToChatMessages(items, {
        keepEmptyMessages: true,
      }).forEach((message) => {
        addConversationMessage(conversationId, message);
      });
    },
    [],
  );

  const invokeSessionControl = useCallback(
    async (
      conversationId: string,
      agentId: string,
      agentSource: AgentSource,
      query: string,
      options: {
        userMessageId?: string;
        sessionControlIntent: "append" | "preempt";
      },
    ) => {
      const currentSession = useChatStore.getState().sessions[conversationId];
      if (!currentSession) {
        throw new Error("Conversation session is unavailable.");
      }
      if (agentSource !== "personal" && agentSource !== "shared") {
        throw new Error(
          "Hub Assistants do not support upstream session control.",
        );
      }
      const response =
        agentSource === "shared"
          ? await invokeHubAgent(
              agentId,
              buildInvokePayload(
                query,
                currentSession,
                conversationId,
                options,
              ),
            )
          : await invokeAgent(
              agentId,
              buildInvokePayload(
                query,
                currentSession,
                conversationId,
                options,
              ),
            );
      if (!response.success) {
        throw new Error(
          response.error?.trim() ||
            `${options.sessionControlIntent} session control failed.`,
        );
      }
      return response;
    },
    [],
  );

  const isAppendAvailableForSession = useCallback(
    (
      currentSession:
        | Pick<AgentSession, "streamState" | "metadata" | "externalSessionRef">
        | null
        | undefined,
    ) => {
      if (currentSession?.streamState !== "streaming" || pendingInterrupt) {
        return false;
      }
      const externalSessionId =
        currentSession.externalSessionRef?.externalSessionId?.trim() ?? "";
      const streamIdentity = readSharedStreamIdentity(currentSession?.metadata);
      const canAppendToRunningTurn = Boolean(
        sessionAppendStatus === "supported" &&
        (!sessionAppendRequiresStreamIdentity ||
          (streamIdentity.threadId && streamIdentity.turnId)),
      );
      return Boolean(externalSessionId) && canAppendToRunningTurn;
    },
    [
      pendingInterrupt,
      sessionAppendRequiresStreamIdentity,
      sessionAppendStatus,
    ],
  );

  const appendMessageToRunningSession = useCallback(
    async (conversationId: string, agentId: string, content: string) => {
      const parsedInput = parseComposerInput(content);
      if (parsedInput.kind !== "message") {
        throw new Error("Append only supports plain text messages.");
      }

      const currentSession = useChatStore.getState().sessions[conversationId];
      const externalSessionId =
        currentSession?.externalSessionRef?.externalSessionId?.trim() ?? "";
      if (currentSession?.streamState !== "streaming" || !externalSessionId) {
        throw new Error(
          "Append requires an active stream with a bound upstream session.",
        );
      }
      if (!isAppendAvailableForSession(currentSession)) {
        throw new Error(
          "The agent is still working. Interrupt it before sending a new message.",
        );
      }

      const trimmedContent = parsedInput.text.trim();
      const operationId = generateUuid();
      const userMessageId = generateUuid();
      const response = await appendSessionMessage(conversationId, {
        content: trimmedContent,
        userMessageId,
        operationId,
        metadata: currentSession?.metadata ?? {},
        ...(currentSession?.workingDirectory
          ? { workingDirectory: currentSession.workingDirectory }
          : {}),
      });
      addCanonicalSessionMessages(conversationId, [response.userMessage]);
      useChatStore.getState().bindExternalSession(conversationId, {
        agentId,
        externalSessionId:
          response.sessionControl?.sessionId?.trim() || externalSessionId,
      });
      toast.info(
        "Message added to current response",
        "Your message was sent to the running upstream session.",
      );
    },
    [addCanonicalSessionMessages, isAppendAvailableForSession],
  );

  const preemptRunningSession = useCallback(
    async (
      conversationId: string,
      agentId: string,
      agentSource: AgentSource,
    ) => {
      const response = await invokeSessionControl(
        conversationId,
        agentId,
        agentSource,
        "",
        {
          sessionControlIntent: "preempt",
        },
      );
      useChatStore
        .getState()
        .cancelMessage(conversationId, { requestRemoteCancel: false });

      if (response.sessionControl?.status === "no_inflight") {
        toast.info(
          "No active response",
          "There is no running response to interrupt.",
        );
        return;
      }

      toast.info(
        "Response interrupted",
        "The current response was interrupted. You can send a new message now.",
      );
    },
    [invokeSessionControl],
  );

  const sendMessageWithCapabilities = useCallback(
    async (
      conversationId: string,
      agentId: string,
      content: string,
      agentSource: AgentSource,
    ) => {
      const parsedInput = parseComposerInput(content);
      if (parsedInput.kind === "command") {
        if (sessionCommandStatus !== "supported") {
          toast.error(
            "Command unavailable",
            "This agent does not expose session command support.",
          );
          throw buildSkippedToastError("Session command is not supported.");
        }

        const currentSession = useChatStore.getState().sessions[conversationId];
        const externalSessionId =
          currentSession?.externalSessionRef?.externalSessionId?.trim() ?? "";
        if (!externalSessionId) {
          toast.error(
            "Command unavailable",
            "This conversation is not bound to an upstream session yet.",
          );
          throw buildSkippedToastError(
            "Session command requires an upstream session.",
          );
        }

        if (agentSource !== "personal" && agentSource !== "shared") {
          throw new Error("Hub Assistants do not support session commands.");
        }
        const operationId = generateUuid();
        const result = await runSessionCommand(conversationId, {
          command: parsedInput.command,
          arguments: parsedInput.arguments,
          prompt: parsedInput.prompt,
          userMessageId: generateUuid(),
          agentMessageId: generateUuid(),
          operationId,
          metadata: currentSession?.metadata ?? {},
          ...(currentSession?.workingDirectory
            ? { workingDirectory: currentSession.workingDirectory }
            : {}),
        });
        addCanonicalSessionMessages(conversationId, [
          result.userMessage,
          result.agentMessage,
        ]);
        toast.success("Command executed", parsedInput.command);
        return;
      }

      const effectiveContent = parsedInput.text;
      const currentSession = useChatStore.getState().sessions[conversationId];
      const isActivelyStreaming =
        currentSession?.streamState === "streaming" ||
        currentSession?.streamState === "continuing";

      if (isHubAssistant(agentId)) {
        if (isActivelyStreaming) {
          toast.info(
            "Interrupt required",
            "The assistant is still working. Interrupt it before sending a new message.",
          );
          throw buildSkippedToastError(
            "Interrupt the current response before sending a new message.",
          );
        }
        await sendHubAssistantMessage(
          conversationId,
          agentId,
          effectiveContent,
        );
        return;
      }

      if (isActivelyStreaming) {
        if (isAppendAvailableForSession(currentSession)) {
          await appendMessageToRunningSession(
            conversationId,
            agentId,
            effectiveContent,
          );
          return;
        }
        toast.info(
          "Interrupt required",
          "The agent is still working. Interrupt it before sending a new message.",
        );
        throw buildSkippedToastError(
          "Interrupt the current response before sending a new message.",
        );
      }

      await sendMessage(
        conversationId,
        agentId,
        effectiveContent,
        agentSource,
        runtimeStatusContract,
      );
    },
    [
      addCanonicalSessionMessages,
      appendMessageToRunningSession,
      buildSkippedToastError,
      isAppendAvailableForSession,
      runtimeStatusContract,
      sendHubAssistantMessage,
      sendMessage,
      sessionCommandStatus,
    ],
  );

  const canAppendToRunningStream = useMemo(
    () => isAppendAvailableForSession(session),
    [isAppendAvailableForSession, session],
  );

  return {
    canAppendToRunningStream,
    preemptRunningSession,
    sendMessageWithCapabilities,
  };
}
