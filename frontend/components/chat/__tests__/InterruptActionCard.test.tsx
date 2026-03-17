import { fireEvent, render } from "@testing-library/react-native";
import React from "react";

import { InterruptActionCard } from "../InterruptActionCard";

describe("InterruptActionCard", () => {
  const baseProps = {
    interruptAction: null,
    questionAnswers: [""],
    onPermissionReply: jest.fn(),
    onQuestionAnswerChange: jest.fn(),
    onQuestionOptionPick: jest.fn(),
    onQuestionReply: jest.fn(),
    onQuestionReject: jest.fn(),
  };

  it("renders permission display message ahead of fallback metadata", () => {
    const { getByText } = render(
      <InterruptActionCard
        {...baseProps}
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
});
