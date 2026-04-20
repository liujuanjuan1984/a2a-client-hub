import { act, type ReactTestRenderer } from "react-test-renderer";

type MockCapabilityStatus = "supported" | "unsupported" | "unknown";

type MockSessionAppend = {
  declared: boolean;
  consumedByHub: boolean;
  status: "supported" | "unsupported";
  routeMode: "unsupported" | "prompt_async" | "turn_steer" | "hybrid";
  requiresStreamIdentity: boolean;
} | null;

type MockInvokeMetadata = {
  fields: { name: string; required: boolean; description?: string | null }[];
} | null;

type MockShortcut = {
  agentId?: string | null;
};

type ChatScreenInterruptChatState = {
  sessions: Record<string, unknown>;
  ensureSession: jest.Mock;
  generateConversationId: jest.Mock;
  sendMessage: jest.Mock;
  cancelMessage: jest.Mock;
  clearPendingInterrupt: jest.Mock;
  replaceRecoveredInterrupts: jest.Mock;
  bindExternalSession: jest.Mock;
  setWorkingDirectory: jest.Mock;
  setInvokeMetadataBindings: jest.Mock;
};

type ChatScreenInterruptExtensionCapabilitiesState = {
  modelSelectionStatus: MockCapabilityStatus;
  interruptRecoveryStatus: MockCapabilityStatus;
  sessionPromptAsyncStatus: MockCapabilityStatus;
  sessionCommandStatus: MockCapabilityStatus;
  sessionAppendStatus: MockCapabilityStatus;
  sessionAppend: MockSessionAppend;
  invokeMetadataStatus: MockCapabilityStatus;
  invokeMetadata: MockInvokeMetadata;
  canShowModelPicker: boolean;
};

type ChatScreenInterruptSessionHistoryState = {
  loadMore: jest.Mock;
  messages: unknown[];
  error: Error | null;
  loading: boolean;
  loadingMore: boolean;
  nextPage: number | undefined;
};

type ChatScreenInterruptShortcutQueryState = {
  shortcuts: MockShortcut[];
  getShortcutsForAgent: jest.Mock;
};

type ChatScreenInterruptHarnessDependencies = {
  conversationId: string;
  hubAssistantAgentId: string;
  baseSession: () => unknown;
  mockAgentStoreState: { activeAgentId: string };
  mockChatState: ChatScreenInterruptChatState;
  mockExtensionCapabilitiesState: ChatScreenInterruptExtensionCapabilitiesState;
  mockSessionHistoryState: ChatScreenInterruptSessionHistoryState;
  mockShortcutQueryState: ChatScreenInterruptShortcutQueryState;
  mockAddShortcut: jest.Mock;
  mockUpdateShortcut: jest.Mock;
  mockRemoveShortcut: jest.Mock;
  mockReplyPermission: jest.Mock;
  mockReplyPermissions: jest.Mock;
  mockReplyQuestion: jest.Mock;
  mockRejectQuestion: jest.Mock;
  mockReplyElicitation: jest.Mock;
  mockAppendSessionMessage: jest.Mock;
  mockListSessionMessagesPage: jest.Mock;
  mockRunSessionCommand: jest.Mock;
  mockRecoverInterrupts: jest.Mock;
  mockInvokeAgent: jest.Mock;
  mockInvokeHubAgent: jest.Mock;
  mockGetHubAssistantProfile: jest.Mock;
  mockRunHubAssistant: jest.Mock;
  mockRecoverHubAssistantInterrupts: jest.Mock;
  mockReplyHubAssistantPermissionInterrupt: jest.Mock;
  mockAddConversationMessage: jest.Mock;
  mockMergeConversationMessages: jest.Mock;
  mockRemoveConversationMessage: jest.Mock;
  mockSetConversationMessages: jest.Mock;
  mockUpdateConversationMessage: jest.Mock;
  mockToastInfo: jest.Mock;
  mockToastSuccess: jest.Mock;
  mockToastError: jest.Mock;
  mockContinueSession: jest.Mock;
};

export function resetChatScreenInterruptHarness(
  deps: ChatScreenInterruptHarnessDependencies,
): void {
  deps.mockAgentStoreState.activeAgentId = "agent-1";
  deps.mockAddShortcut.mockReset().mockResolvedValue(undefined);
  deps.mockUpdateShortcut.mockReset().mockResolvedValue(undefined);
  deps.mockRemoveShortcut.mockReset().mockResolvedValue(undefined);
  deps.mockReplyPermission.mockReset();
  deps.mockReplyPermissions.mockReset();
  deps.mockReplyQuestion.mockReset();
  deps.mockRejectQuestion.mockReset();
  deps.mockReplyElicitation.mockReset();
  deps.mockAddConversationMessage.mockReset();
  deps.mockMergeConversationMessages.mockReset();
  deps.mockRemoveConversationMessage.mockReset();
  deps.mockSetConversationMessages.mockReset();
  deps.mockUpdateConversationMessage.mockReset();
  deps.mockToastInfo.mockReset();
  deps.mockToastSuccess.mockReset();
  deps.mockToastError.mockReset();
  deps.mockContinueSession.mockReset();
  deps.mockListSessionMessagesPage.mockReset().mockResolvedValue({
    items: [],
    pageInfo: {
      hasMoreBefore: false,
      nextBefore: null,
    },
  });
  deps.mockChatState.ensureSession.mockReset();
  deps.mockChatState.generateConversationId
    .mockReset()
    .mockReturnValue("conversation-next");
  deps.mockChatState.sendMessage.mockReset();
  deps.mockChatState.cancelMessage.mockReset();
  deps.mockChatState.clearPendingInterrupt.mockReset();
  deps.mockChatState.replaceRecoveredInterrupts.mockReset();
  deps.mockChatState.bindExternalSession.mockReset();
  deps.mockChatState.setWorkingDirectory.mockReset();
  deps.mockChatState.setInvokeMetadataBindings.mockReset();
  deps.mockInvokeAgent.mockReset().mockResolvedValue({
    success: true,
    sessionControl: {
      intent: "append",
      status: "accepted",
      sessionId: "ses-upstream-1",
    },
  });
  deps.mockInvokeHubAgent.mockReset().mockResolvedValue({ success: true });
  deps.mockAppendSessionMessage.mockReset();
  deps.mockRunSessionCommand.mockReset();
  deps.mockGetHubAssistantProfile.mockReset().mockResolvedValue({
    id: deps.hubAssistantAgentId,
    name: "A2A Client Hub Assistant",
    description: "Hub Assistant",
    runtime: "swival",
    configured: true,
    resources: ["agents", "followups", "jobs", "sessions"],
    tools: [],
  });
  deps.mockRunHubAssistant.mockReset().mockResolvedValue({
    status: "completed",
    answer: "Hub Assistant reply",
    exhausted: false,
    runtime: "swival",
    resources: ["agents", "followups", "jobs", "sessions"],
    tools: ["hub_assistant.jobs.list"],
    write_tools_enabled: false,
    interrupt: null,
  });
  deps.mockRecoverHubAssistantInterrupts
    .mockReset()
    .mockResolvedValue({ items: [] });
  deps.mockReplyHubAssistantPermissionInterrupt.mockReset().mockResolvedValue({
    status: "completed",
    answer: "Write approval was handled.",
    exhausted: false,
    runtime: "swival",
    resources: ["agents", "followups", "jobs", "sessions"],
    tools: ["hub_assistant.jobs.pause"],
    write_tools_enabled: true,
    interrupt: null,
  });
  deps.mockRecoverInterrupts.mockReset().mockResolvedValue({ items: [] });
  deps.mockAddConversationMessage.mockReset();
  deps.mockUpdateConversationMessage.mockReset();
  deps.mockExtensionCapabilitiesState.modelSelectionStatus = "supported";
  deps.mockExtensionCapabilitiesState.interruptRecoveryStatus = "supported";
  deps.mockExtensionCapabilitiesState.sessionPromptAsyncStatus = "supported";
  deps.mockExtensionCapabilitiesState.sessionCommandStatus = "supported";
  deps.mockExtensionCapabilitiesState.sessionAppendStatus = "supported";
  deps.mockExtensionCapabilitiesState.sessionAppend = {
    declared: true,
    consumedByHub: true,
    status: "supported",
    routeMode: "prompt_async",
    requiresStreamIdentity: false,
  };
  deps.mockExtensionCapabilitiesState.invokeMetadataStatus = "unsupported";
  deps.mockExtensionCapabilitiesState.invokeMetadata = null;
  deps.mockExtensionCapabilitiesState.canShowModelPicker = true;
  deps.mockSessionHistoryState.loadMore.mockReset();
  deps.mockSessionHistoryState.messages = [];
  deps.mockSessionHistoryState.error = null;
  deps.mockSessionHistoryState.loading = false;
  deps.mockSessionHistoryState.loadingMore = false;
  deps.mockSessionHistoryState.nextPage = undefined;
  deps.mockShortcutQueryState.shortcuts = [];
  deps.mockShortcutQueryState.getShortcutsForAgent.mockClear();
  deps.mockShortcutQueryState.getShortcutsForAgent.mockImplementation(
    (agentId: string | null) => {
      if (!agentId) {
        return deps.mockShortcutQueryState.shortcuts.filter(
          (item) => !item.agentId,
        );
      }
      return deps.mockShortcutQueryState.shortcuts.filter(
        (item) => !item.agentId || item.agentId === agentId,
      );
    },
  );
  deps.mockContinueSession.mockResolvedValue({});
  deps.mockReplyPermission.mockResolvedValue({ ok: true, requestId: "perm-1" });
  deps.mockReplyPermissions.mockResolvedValue({
    ok: true,
    requestId: "perms-1",
  });
  deps.mockReplyQuestion.mockResolvedValue({ ok: true, requestId: "q-1" });
  deps.mockRejectQuestion.mockResolvedValue({ ok: true, requestId: "q-1" });
  deps.mockReplyElicitation.mockResolvedValue({ ok: true, requestId: "eli-1" });
  deps.mockChatState.sessions = {
    [deps.conversationId]: deps.baseSession(),
  };
  global.requestAnimationFrame = ((callback: FrameRequestCallback) => {
    callback(0);
    return 0;
  }) as unknown as (callback: FrameRequestCallback) => number;
}

export function cleanupChatScreenInterruptTree(
  renderedTree: ReactTestRenderer | null,
): ReactTestRenderer | null {
  if (renderedTree) {
    act(() => {
      renderedTree.unmount();
    });
  }
  jest.useRealTimers();
  return null;
}
