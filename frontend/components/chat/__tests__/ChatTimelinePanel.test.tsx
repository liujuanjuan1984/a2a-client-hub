import { render } from "@testing-library/react-native";
import React from "react";

import { ChatTimelinePanel } from "@/components/chat/ChatTimelinePanel";
import { createAgentSession, type AgentSession } from "@/lib/chat-utils";

jest.mock("@/components/chat/ChatMessageItem", () => ({
  ChatMessageItem: () => null,
}));

jest.mock("@/components/chat/InterruptActionCard", () => ({
  InterruptActionCard: () => null,
}));

jest.mock("@/components/ui/Button", () => ({
  Button: () => null,
}));

const buildSession = (overrides: Partial<AgentSession> = {}): AgentSession => ({
  ...createAgentSession("agent-1"),
  ...overrides,
});

describe("ChatTimelinePanel", () => {
  it("shows recoverable upstream completion diagnostics without spinner", () => {
    const screen = render(
      <ChatTimelinePanel
        listRef={{ current: null }}
        messages={[]}
        session={buildSession({ streamState: "recoverable" })}
        historyNextPage={null}
        historyLoadingMore={false}
        historyPaused={false}
        onLoadEarlierHistory={jest.fn()}
        historyLoading={false}
        historyError={null}
        recoverableStatusMessage="Connection lost after upstream completion. Retry will backfill any missing final chunks."
        recoverableStatusBusy={false}
        onCaptureContentSizeAnchor={jest.fn()}
        onLoadBlockContent={jest.fn().mockResolvedValue(true)}
        onRetry={jest.fn()}
        onInterruptStream={jest.fn()}
        onListContentSizeChange={jest.fn()}
        onListScroll={jest.fn()}
        pendingInterrupt={null}
        pendingInterruptCount={0}
        interruptAction={null}
        questionAnswers={[]}
        structuredResponseInput=""
        onPermissionReply={jest.fn()}
        onPermissionsReply={jest.fn()}
        onQuestionAnswerChange={jest.fn()}
        onQuestionOptionPick={jest.fn()}
        onQuestionReply={jest.fn()}
        onQuestionReject={jest.fn()}
        onStructuredResponseChange={jest.fn()}
        onElicitationReply={jest.fn()}
      />,
    );

    expect(
      screen.getByText(
        "Connection lost after upstream completion. Retry will backfill any missing final chunks.",
      ),
    ).toBeTruthy();
  });
});
