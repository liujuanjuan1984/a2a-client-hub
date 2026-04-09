import type { PendingRuntimeInterrupt } from "@/lib/api/chat-utils";
import { apiRequest } from "@/lib/api/client";

export const SELF_MANAGEMENT_BUILT_IN_AGENT_ID = "self-management-assistant";
export const SELF_MANAGEMENT_BUILT_IN_AGENT_CARD_URL =
  "builtin://self-management-assistant";

export const isSelfManagementBuiltInAgent = (agentId?: string | null) =>
  (agentId ?? "").trim() === SELF_MANAGEMENT_BUILT_IN_AGENT_ID;

type SelfManagementBuiltInAgentToolResponse = {
  operation_id: string;
  tool_name: string;
  description: string;
  confirmation_policy: string;
};

export type SelfManagementBuiltInAgentProfileResponse = {
  id: string;
  name: string;
  description: string;
  runtime: string;
  configured: boolean;
  resources: string[];
  tools: SelfManagementBuiltInAgentToolResponse[];
};

type SelfManagementBuiltInAgentInterruptResponse = {
  requestId: string;
  type: "permission";
  phase: "asked";
  details: {
    permission?: string | null;
    patterns?: string[];
    displayMessage?: string | null;
  };
};

type SelfManagementBuiltInAgentRecoveredInterruptResponse = {
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

type SelfManagementBuiltInAgentRunResponse = {
  status: "completed" | "interrupted";
  answer: string | null;
  exhausted: boolean;
  runtime: string;
  resources: string[];
  tools: string[];
  write_tools_enabled: boolean;
  interrupt?: SelfManagementBuiltInAgentInterruptResponse | null;
};

export const getSelfManagementBuiltInAgentProfile = () =>
  apiRequest<SelfManagementBuiltInAgentProfileResponse>(
    "/me/self-management/agent",
  );

export const runSelfManagementBuiltInAgent = (payload: {
  conversationId: string;
  message: string;
  allow_write_tools?: boolean;
}) =>
  apiRequest<
    SelfManagementBuiltInAgentRunResponse,
    { conversationId: string; message: string; allow_write_tools?: boolean }
  >("/me/self-management/agent:run", {
    method: "POST",
    body: payload,
  });

export const replySelfManagementBuiltInAgentPermissionInterrupt = (payload: {
  requestId: string;
  reply: "once" | "always" | "reject";
}) =>
  apiRequest<
    SelfManagementBuiltInAgentRunResponse,
    { requestId: string; reply: "once" | "always" | "reject" }
  >("/me/self-management/agent/interrupts/permission:reply", {
    method: "POST",
    body: payload,
  });

export const recoverSelfManagementBuiltInAgentInterrupts = async (payload: {
  conversationId: string;
}) => {
  const response = await apiRequest<{
    items?: SelfManagementBuiltInAgentRecoveredInterruptResponse[];
  }>("/me/self-management/agent/interrupts:recover", {
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
    | SelfManagementBuiltInAgentInterruptResponse
    | SelfManagementBuiltInAgentRecoveredInterruptResponse,
) => ({
  permission: interrupt.details.permission ?? null,
  patterns: interrupt.details.patterns ?? [],
  displayMessage: interrupt.details.displayMessage ?? null,
});

export const toPendingRuntimeInterrupt = (
  interrupt: SelfManagementBuiltInAgentInterruptResponse,
): PendingRuntimeInterrupt => ({
  requestId: interrupt.requestId,
  type: interrupt.type,
  phase: interrupt.phase,
  details: buildInterruptDetails(interrupt),
});

const toRecoveredPendingRuntimeInterrupt = (
  interrupt: SelfManagementBuiltInAgentRecoveredInterruptResponse,
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
