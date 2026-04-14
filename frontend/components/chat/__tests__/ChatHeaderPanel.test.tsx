import { render } from "@testing-library/react-native";
import React from "react";

import { ChatHeaderPanel } from "../ChatHeaderPanel";

import { type AgentSession } from "@/lib/chat-utils";
import { type AgentConfig } from "@/store/agents";

jest.mock("@/components/ui/BackButton", () => ({
  BackButton: () => null,
}));

describe("ChatHeaderPanel", () => {
  it("renders a compact generic agent info panel without discovery-specific details", () => {
    const agent = {
      id: "agent-1",
      name: "Planner",
      cardUrl: "https://example.com/.well-known/agent-card.json",
      source: "personal",
    } as AgentConfig;
    const session = {
      agentId: "agent-1",
      title: null,
      source: "manual",
      lastActiveAt: "2026-04-12T00:00:00.000Z",
      runtimeStatus: "ready",
      transport: "sse",
      inputModes: ["text"],
      outputModes: ["text"],
      metadata: {},
      workingDirectory: "/workspace/app",
      messages: [],
      pendingInterrupts: [],
      pendingInterrupt: null,
      streamState: "idle",
      externalSessionRef: null,
    } as unknown as AgentSession;

    const screen = render(
      <ChatHeaderPanel
        topInset={0}
        agent={agent}
        conversationId="conv-1"
        sessionSource="manual"
        session={session}
        showDetails
        onToggleDetails={() => {}}
        onOpenSessionPicker={() => {}}
        onTestConnection={() => {}}
        testingConnection={false}
        modelSelectionStatus="supported"
        providerDiscoveryStatus="unknown"
        interruptRecoveryStatus="unsupported"
        sessionPromptAsyncStatus="supported"
        sessionAppendStatus="supported"
        sessionCommandStatus="unsupported"
        sessionShellStatus="unknown"
        invokeMetadataStatus="supported"
      />,
    );

    expect(screen.getByText("Agent Card")).toBeTruthy();
    expect(screen.getByText("Check")).toBeTruthy();
    expect(screen.getByText("Modes")).toBeTruthy();
    expect(screen.getByText("sse").props.numberOfLines).toBe(1);
    expect(screen.getByText("text -> text")).toBeTruthy();
    expect(screen.queryByText("Diagnostics")).toBeNull();
    expect(screen.queryByText("Test")).toBeNull();
    expect(screen.queryByText("Codex Discovery")).toBeNull();
    expect(screen.queryByText("Browse")).toBeNull();
    expect(
      screen.queryByText("This agent does not declare Codex discovery."),
    ).toBeNull();
    expect(screen.getByText("Capabilities")).toBeTruthy();
    expect(screen.getByText("Model Selection")).toBeTruthy();
    expect(screen.getByText("Streaming Append")).toBeTruthy();
    expect(screen.getByText("Prompt Async")).toBeTruthy();
    expect(screen.getByText("Invoke Metadata")).toBeTruthy();
    expect(screen.queryByText("Provider Discovery")).toBeNull();
    expect(screen.queryByText("Interrupt Recovery")).toBeNull();
    expect(screen.queryByText("Session Command")).toBeNull();
    expect(screen.queryByText("Session Shell")).toBeNull();
    expect(screen.queryByText("Available")).toBeNull();
    expect(screen.queryByText("Unknown")).toBeNull();
    expect(screen.queryByText("Unavailable")).toBeNull();
    expect(screen.queryByText("IN: text")).toBeNull();
    expect(screen.queryByText("OUT: text")).toBeNull();
  });
});
