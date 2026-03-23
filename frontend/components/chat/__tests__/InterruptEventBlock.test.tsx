import { render } from "@testing-library/react-native";
import React from "react";

import { InterruptEventBlock } from "../blocks/InterruptEventBlock";

import { type MessageBlock } from "@/lib/api/chat-utils";

describe("InterruptEventBlock", () => {
  it("renders asked permission interrupt with action badge and targets", () => {
    const block: MessageBlock = {
      id: "interrupt-asked-1",
      type: "interrupt_event",
      content: "Agent requested authorization: read.\nTargets: /repo/.env",
      isFinished: true,
      interrupt: {
        requestId: "perm-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "read",
          patterns: ["/repo/.env"],
          displayMessage: null,
        },
      },
      createdAt: "2026-03-23T00:00:00.000Z",
      updatedAt: "2026-03-23T00:00:00.000Z",
    };

    const screen = render(
      <InterruptEventBlock
        block={block}
        fallbackBlockId="interrupt-fallback-1"
        isFirst
      />,
    );

    expect(screen.getByText("Interrupt")).toBeTruthy();
    expect(screen.getByText("Authorization requested")).toBeTruthy();
    expect(screen.getByText("Action Required")).toBeTruthy();
    expect(screen.getByText("Permission")).toBeTruthy();
    expect(screen.getByText("read")).toBeTruthy();
    expect(screen.getByText("Targets: /repo/.env")).toBeTruthy();
  });

  it("renders resolved interrupt with handled badge", () => {
    const block: MessageBlock = {
      id: "interrupt-resolved-1",
      type: "interrupt_event",
      content: "Authorization request was handled. Agent resumed.",
      isFinished: true,
      interrupt: {
        requestId: "perm-2",
        type: "permission",
        phase: "resolved",
        resolution: "replied",
      },
      createdAt: "2026-03-23T00:00:00.000Z",
      updatedAt: "2026-03-23T00:00:00.000Z",
    };

    const screen = render(
      <InterruptEventBlock
        block={block}
        fallbackBlockId="interrupt-fallback-2"
        isFirst
      />,
    );

    expect(screen.getByText("Authorization update")).toBeTruthy();
    expect(screen.getByText("Handled")).toBeTruthy();
    expect(
      screen.getByText("Authorization request was handled. Agent resumed."),
    ).toBeTruthy();
  });
});
