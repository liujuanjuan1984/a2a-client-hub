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

  it("renders expired interrupt with expired badge", () => {
    const block: MessageBlock = {
      id: "interrupt-expired-1",
      type: "interrupt_event",
      content: "Authorization request expired. Interrupt closed.",
      isFinished: true,
      interrupt: {
        requestId: "perm-3",
        type: "permission",
        phase: "resolved",
        resolution: "expired",
      },
      createdAt: "2026-03-23T00:00:00.000Z",
      updatedAt: "2026-03-23T00:00:00.000Z",
    };

    const screen = render(
      <InterruptEventBlock
        block={block}
        fallbackBlockId="interrupt-fallback-expired"
        isFirst
      />,
    );

    expect(screen.getByText("Authorization update")).toBeTruthy();
    expect(screen.getByText("Expired")).toBeTruthy();
    expect(
      screen.getByText("Authorization request expired. Interrupt closed."),
    ).toBeTruthy();
  });

  it("renders asked permissions interrupt with structured payload details", () => {
    const block: MessageBlock = {
      id: "interrupt-asked-2",
      type: "interrupt_event",
      content:
        'Approve the requested workspace permissions.\nRequested permissions: {"fileSystem":{"write":["/repo"]}}',
      isFinished: true,
      interrupt: {
        requestId: "perms-1",
        type: "permissions",
        phase: "asked",
        details: {
          displayMessage: "Approve the requested workspace permissions.",
          permissions: {
            fileSystem: { write: ["/repo"] },
          },
        },
      },
      createdAt: "2026-03-27T00:00:00.000Z",
      updatedAt: "2026-03-27T00:00:00.000Z",
    };

    const screen = render(
      <InterruptEventBlock
        block={block}
        fallbackBlockId="interrupt-fallback-3"
        isFirst
      />,
    );

    expect(screen.getByText("Permissions approval requested")).toBeTruthy();
    expect(screen.getByText("Action Required")).toBeTruthy();
    expect(screen.getByText("Requested Permissions")).toBeTruthy();
    expect(screen.getAllByText(/fileSystem/).length).toBeGreaterThan(0);
  });

  it("renders asked elicitation interrupt context fields", () => {
    const block: MessageBlock = {
      id: "interrupt-asked-3",
      type: "interrupt_event",
      content:
        "Select the target folder.\nMode: form\nServer: workspace-server\nURL: https://example.com/form",
      isFinished: true,
      interrupt: {
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
      },
      createdAt: "2026-03-27T00:00:00.000Z",
      updatedAt: "2026-03-27T00:00:00.000Z",
    };

    const screen = render(
      <InterruptEventBlock
        block={block}
        fallbackBlockId="interrupt-fallback-4"
        isFirst
      />,
    );

    expect(screen.getByText("Structured input requested")).toBeTruthy();
    expect(screen.getByText("Action Required")).toBeTruthy();
    expect(screen.getByText("Mode: form")).toBeTruthy();
    expect(screen.getByText("Server: workspace-server")).toBeTruthy();
    expect(screen.getByText("Requested Schema")).toBeTruthy();
  });
});
