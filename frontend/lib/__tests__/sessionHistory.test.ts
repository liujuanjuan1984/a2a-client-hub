import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";

describe("session history mapping", () => {
  it("maps canonical ids from block-based history", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "1c7cf18e-4936-4de0-84f5-edf2e636ed41",
        role: "assistant",
        created_at: "2026-02-14T00:00:00.000Z",
        blocks: [
          {
            id: "block-1",
            messageId: "1c7cf18e-4936-4de0-84f5-edf2e636ed41",
            seq: 1,
            type: "text",
            content: "final",
            isFinished: true,
          },
        ],
      },
    ]);

    expect(mapped[0]).toMatchObject({
      id: "1c7cf18e-4936-4de0-84f5-edf2e636ed41",
      role: "agent",
      content: "final",
    });
  });

  it("builds one text block for agent message content", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "2fbe098d-7af0-4bf9-8402-a1778aeeeb2f",
        role: "assistant",
        created_at: "2026-02-14T00:00:01.000Z",
        metadata: {},
        blocks: [
          {
            id: "block-2",
            messageId: "2fbe098d-7af0-4bf9-8402-a1778aeeeb2f",
            seq: 1,
            type: "text",
            content: "final",
            isFinished: true,
          },
        ],
      },
    ]);

    expect(mapped[0]?.blocks).toEqual([
      {
        id: "block-2",
        type: "text",
        content: "final",
        isFinished: true,
        createdAt: "2026-02-14T00:00:01.000Z",
        updatedAt: "2026-02-14T00:00:01.000Z",
      },
    ]);
  });

  it("removes json-style quoting from legacy agent contents", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "3b9bdc78-93f3-4489-82e5-6967e35ecf36",
        role: "assistant",
        content: '"Task(artifacts=[Artifact(artifact_id="id")])"',
        created_at: "2026-02-14T00:00:02.000Z",
        metadata: {},
      },
    ]);

    expect(mapped[0]).toMatchObject({
      role: "agent",
      content: 'Task(artifacts=[Artifact(artifact_id="id")])',
      blocks: [
        {
          id: "3b9bdc78-93f3-4489-82e5-6967e35ecf36:1",
          type: "text",
          content: 'Task(artifacts=[Artifact(artifact_id="id")])',
          isFinished: true,
          createdAt: "2026-02-14T00:00:02.000Z",
          updatedAt: "2026-02-14T00:00:02.000Z",
        },
      ],
    });
  });
});
