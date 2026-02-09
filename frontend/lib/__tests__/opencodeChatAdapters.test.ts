import { mapOpencodeMessagesToChatMessages } from "@/lib/opencodeChatAdapters";

describe("mapOpencodeMessagesToChatMessages", () => {
  test("maps A2A Message parts into chat content (no stringify fallback)", () => {
    const items = [
      {
        kind: "message",
        messageId: "m-1",
        role: "user",
        parts: [{ kind: "text", text: "Hello" }],
        metadata: {
          opencode: {
            raw: {
              info: {
                time: { created: 1770636900085 },
              },
            },
          },
        },
      },
      {
        kind: "message",
        messageId: "m-2",
        // Some upstreams may not fill role correctly; fall back to metadata.opencode.raw.info.role.
        role: "agent",
        parts: [
          { kind: "text", text: "Hi " },
          { kind: "text", text: "there" },
        ],
        metadata: {
          opencode: {
            raw: {
              info: { role: "assistant" },
            },
          },
        },
      },
    ];

    const mapped = mapOpencodeMessagesToChatMessages(items);
    expect(mapped).toHaveLength(2);
    expect(mapped[0].id).toBe("opencode:m-1");
    expect(mapped[0].role).toBe("user");
    expect(mapped[0].content).toBe("Hello");
    expect(mapped[0].createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);

    expect(mapped[1].id).toBe("opencode:m-2");
    expect(mapped[1].role).toBe("agent");
    expect(mapped[1].content).toBe("Hi there");
  });
});
