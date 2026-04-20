import type { PendingRuntimeInterrupt } from "@/lib/api/chat-utils";
import { apiRequest } from "@/lib/api/client";

export const HUB_ASSISTANT_ID = "hub-assistant";

export const isHubAssistant = (agentId?: string | null) =>
  (agentId ?? "").trim() === HUB_ASSISTANT_ID;

type HubAssistantToolResponse = {
  operation_id: string;
  tool_name: string;
  description: string;
  confirmation_policy: string;
};

export type HubAssistantProfileResponse = {
  id: string;
  name: string;
  description: string;
  runtime: string;
  configured: boolean;
  resources: string[];
  tools: HubAssistantToolResponse[];
};

type HubAssistantInterruptResponse = {
  requestId: string;
  type: "permission";
  phase: "asked";
  details: {
    permission?: string | null;
    patterns?: string[];
    displayMessage?: string | null;
  };
};

type HubAssistantRecoveredInterruptResponse = {
  requestId: string;
  sessionId: string;
  type: "permission";
  phase: "asked";
  details: {
    permission?: string | null;
    patterns?: string[];
    displayMessage?: string | null;
  };
};

type HubAssistantRunResponse = {
  status: "accepted" | "completed" | "interrupted";
  answer: string | null;
  exhausted: boolean;
  runtime: string;
  resources: string[];
  tools: string[];
  write_tools_enabled: boolean;
  interrupt?: HubAssistantInterruptResponse | null;
  continuation?: {
    phase: "running";
    agentMessageId: string;
  } | null;
};

export const getHubAssistantProfile = () =>
  apiRequest<HubAssistantProfileResponse>("/me/hub-assistant");

export const runHubAssistant = (payload: {
  conversationId: string;
  message: string;
  userMessageId?: string;
  agentMessageId?: string;
  allow_write_tools?: boolean;
}) =>
  apiRequest<
    HubAssistantRunResponse,
    {
      conversationId: string;
      message: string;
      userMessageId?: string;
      agentMessageId?: string;
      allow_write_tools?: boolean;
    }
  >("/me/hub-assistant:run", {
    method: "POST",
    body: payload,
  });

export const replyHubAssistantPermissionInterrupt = (payload: {
  requestId: string;
  reply: "once" | "always" | "reject";
  agentMessageId?: string;
}) =>
  apiRequest<
    HubAssistantRunResponse,
    {
      requestId: string;
      reply: "once" | "always" | "reject";
      agentMessageId?: string;
    }
  >("/me/hub-assistant/interrupts/permission:reply", {
    method: "POST",
    body: payload,
  });

export const recoverHubAssistantInterrupts = async (payload: {
  conversationId: string;
}) => {
  const response = await apiRequest<{
    items?: HubAssistantRecoveredInterruptResponse[];
  }>("/me/hub-assistant/interrupts:recover", {
    method: "POST",
    body: payload,
  });
  const items = Array.isArray(response.items) ? response.items : [];
  return {
    items: items
      .map((interrupt) => toRecoveredPendingRuntimeInterrupt(interrupt))
      .filter((interrupt): interrupt is PendingRuntimeInterrupt =>
        Boolean(interrupt),
      ),
  };
};

const buildInterruptDetails = (
  interrupt:
    | HubAssistantInterruptResponse
    | HubAssistantRecoveredInterruptResponse,
) => ({
  permission: interrupt.details.permission ?? null,
  patterns: interrupt.details.patterns ?? [],
  displayMessage: interrupt.details.displayMessage ?? null,
});

export const toPendingRuntimeInterrupt = (
  interrupt: HubAssistantInterruptResponse,
): PendingRuntimeInterrupt => ({
  requestId: interrupt.requestId,
  type: interrupt.type,
  phase: interrupt.phase,
  details: buildInterruptDetails(interrupt),
});

const toRecoveredPendingRuntimeInterrupt = (
  interrupt: HubAssistantRecoveredInterruptResponse,
): PendingRuntimeInterrupt | null => {
  const requestId = interrupt.requestId.trim();
  const sessionId = interrupt.sessionId.trim();
  if (!requestId || !sessionId) {
    return null;
  }
  return {
    requestId,
    sessionId,
    type: interrupt.type,
    phase: interrupt.phase,
    source: "recovery",
    taskId: null,
    contextId: null,
    expiresAt: null,
    details: buildInterruptDetails(interrupt),
  };
};
