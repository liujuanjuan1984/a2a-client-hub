import {
  getOpencodeMessageRole,
  getOpencodeMessageText,
  getOpencodeSessionId,
  getOpencodeSessionTitle,
} from "@/lib/opencodeAdapters";

describe("opencodeAdapters", () => {
  it("extracts session id/title from common fields", () => {
    expect(getOpencodeSessionId({ id: "s-1" })).toBe("s-1");
    expect(getOpencodeSessionTitle({ title: "Hello" })).toBe("Hello");
    expect(getOpencodeSessionTitle({ id: "s-2" })).toBe("s-2");
  });

  it("extracts session title from A2A Task metadata contract", () => {
    expect(
      getOpencodeSessionTitle({
        kind: "task",
        id: "s-1",
        contextId: "s-1",
        metadata: { opencode: { title: "Untitled session" } },
      }),
    ).toBe("Untitled session");
  });

  it("extracts message role/text from common fields", () => {
    expect(getOpencodeMessageRole({ role: "assistant" })).toBe("assistant");
    expect(getOpencodeMessageText({ text: "hi" })).toBe("hi");
    expect(getOpencodeMessageText({ content: "hello" })).toBe("hello");
  });

  it("extracts message role/text from A2A Message shapes", () => {
    const a2aMsg = {
      kind: "message",
      messageId: "m-1",
      role: "agent", // some upstreams set this to agent; prefer metadata raw role when present
      parts: [{ kind: "text", text: "Hello from parts" }],
      metadata: {
        opencode: {
          raw: {
            info: { role: "user", time: { created: 1770636900085 } },
            parts: [{ type: "text", text: "Hello from raw parts" }],
          },
        },
      },
    };
    expect(getOpencodeMessageRole(a2aMsg)).toBe("user");
    expect(getOpencodeMessageText(a2aMsg)).toBe("Hello from parts");
  });

  it("falls back safely for unknown shapes", () => {
    expect(getOpencodeSessionTitle(null)).toBe("Session");
    expect(getOpencodeMessageRole(null)).toBe("message");
    expect(getOpencodeMessageText({})).toContain("{");
  });
});
