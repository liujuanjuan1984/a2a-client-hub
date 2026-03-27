import { fireEvent, render } from "@testing-library/react-native";
import React from "react";

import { InterruptActionCard } from "../InterruptActionCard";

describe("InterruptActionCard", () => {
  const baseProps = {
    interruptAction: null,
    questionAnswers: [""],
    structuredResponseInput: "",
    onPermissionReply: jest.fn(),
    onPermissionsReply: jest.fn(),
    onQuestionAnswerChange: jest.fn(),
    onQuestionOptionPick: jest.fn(),
    onQuestionReply: jest.fn(),
    onQuestionReject: jest.fn(),
    onStructuredResponseChange: jest.fn(),
    onElicitationReply: jest.fn(),
  };

  it("renders permission display message ahead of fallback metadata", () => {
    const { getByText } = render(
      <InterruptActionCard
        {...baseProps}
        pendingInterruptCount={1}
        pendingInterrupt={{
          requestId: "perm-1",
          type: "permission",
          phase: "asked",
          details: {
            permission: "approval",
            patterns: ["/repo/.env"],
            displayMessage: "Agent wants to read the environment file.",
          },
        }}
      />,
    );

    expect(getByText("Agent wants to read the environment file.")).toBeTruthy();
    expect(getByText(/Permission:/)).toBeTruthy();
    expect(getByText(/approval/)).toBeTruthy();
    expect(getByText("• /repo/.env")).toBeTruthy();
  });

  it("renders question description and option picks", () => {
    const onQuestionOptionPick = jest.fn();
    const { getByText } = render(
      <InterruptActionCard
        {...baseProps}
        pendingInterruptCount={1}
        onQuestionOptionPick={onQuestionOptionPick}
        pendingInterrupt={{
          requestId: "q-1",
          type: "question",
          phase: "asked",
          details: {
            displayMessage: "Please confirm how the agent should continue.",
            questions: [
              {
                header: "Approval",
                question: "Proceed with deployment?",
                description: "This will update the production service.",
                options: [{ label: "Yes", value: "yes", description: null }],
              },
            ],
          },
        }}
      />,
    );

    expect(
      getByText("Please confirm how the agent should continue."),
    ).toBeTruthy();
    expect(getByText("Approval")).toBeTruthy();
    expect(getByText("Proceed with deployment?")).toBeTruthy();
    expect(getByText("This will update the production service.")).toBeTruthy();

    fireEvent.press(getByText("Yes"));
    expect(onQuestionOptionPick).toHaveBeenCalledWith(0, "yes");
  });

  it("renders permissions interrupt editor and scope actions", () => {
    const onPermissionsReply = jest.fn();
    const onStructuredResponseChange = jest.fn();
    const { getByText, getByTestId } = render(
      <InterruptActionCard
        {...baseProps}
        pendingInterruptCount={2}
        structuredResponseInput='{"fileSystem":{"write":["/workspace/project"]}}'
        onPermissionsReply={onPermissionsReply}
        onStructuredResponseChange={onStructuredResponseChange}
        pendingInterrupt={{
          requestId: "perm-v2-1",
          type: "permissions",
          phase: "asked",
          details: {
            displayMessage: "Approve the requested workspace permissions.",
            permissions: {
              fileSystem: { write: ["/workspace/project"] },
            },
          },
        }}
      />,
    );

    expect(getByText("Permissions Required")).toBeTruthy();
    expect(
      getByText("Approve the requested workspace permissions."),
    ).toBeTruthy();
    expect(getByText("Requested Permissions")).toBeTruthy();

    fireEvent.changeText(
      getByTestId("interrupt-permissions-json-input"),
      '{"network":{"fetch":["https://example.com"]}}',
    );
    expect(onStructuredResponseChange).toHaveBeenCalledWith(
      '{"network":{"fetch":["https://example.com"]}}',
    );

    fireEvent.press(getByTestId("interrupt-permissions-turn"));
    fireEvent.press(getByTestId("interrupt-permissions-session"));

    expect(onPermissionsReply).toHaveBeenNthCalledWith(1, "turn");
    expect(onPermissionsReply).toHaveBeenNthCalledWith(2, "session");
  });

  it("renders elicitation interrupt details and response actions", () => {
    const onElicitationReply = jest.fn();
    const onStructuredResponseChange = jest.fn();
    const { getByText, getByTestId } = render(
      <InterruptActionCard
        {...baseProps}
        pendingInterruptCount={1}
        structuredResponseInput='{"folder":"docs"}'
        onElicitationReply={onElicitationReply}
        onStructuredResponseChange={onStructuredResponseChange}
        pendingInterrupt={{
          requestId: "eli-1",
          type: "elicitation",
          phase: "asked",
          details: {
            displayMessage: "Select the target folder.",
            mode: "form",
            serverName: "workspace-server",
            url: "https://example.com/form",
            requestedSchema: {
              type: "object",
              properties: { folder: { type: "string" } },
            },
          },
        }}
      />,
    );

    expect(getByText("Structured Input Required")).toBeTruthy();
    expect(getByText("Select the target folder.")).toBeTruthy();
    expect(getByText("Mode: form")).toBeTruthy();
    expect(getByText("Server: workspace-server")).toBeTruthy();
    expect(getByText("URL: https://example.com/form")).toBeTruthy();
    expect(getByText("Requested Schema")).toBeTruthy();

    fireEvent.changeText(
      getByTestId("interrupt-elicitation-json-input"),
      '{"folder":"src"}',
    );
    expect(onStructuredResponseChange).toHaveBeenCalledWith('{"folder":"src"}');

    fireEvent.press(getByTestId("interrupt-elicitation-accept"));
    fireEvent.press(getByTestId("interrupt-elicitation-decline"));
    fireEvent.press(getByTestId("interrupt-elicitation-cancel"));

    expect(onElicitationReply).toHaveBeenNthCalledWith(1, "accept");
    expect(onElicitationReply).toHaveBeenNthCalledWith(2, "decline");
    expect(onElicitationReply).toHaveBeenNthCalledWith(3, "cancel");
  });
});
