import { resolvePersistedHistoryContinuation } from "@/hooks/useContinuationConvergence";
import { type ChatMessage } from "@/lib/api/chat-utils";

const createMessage = (
  id: string,
  status: ChatMessage["status"],
): ChatMessage => ({
  id,
  role: "agent",
  content: status === "error" ? "Continuation failed." : "Result",
  createdAt: "2026-04-21T00:00:00.000Z",
  status,
});

describe("resolvePersistedHistoryContinuation", () => {
  it("waits while the target agent message is still streaming", () => {
    const event = resolvePersistedHistoryContinuation({
      targetMessageId: "agent-1",
      messages: [createMessage("agent-1", "streaming")],
    });

    expect(event).toBeNull();
  });

  it("ignores unrelated terminal agent messages", () => {
    const event = resolvePersistedHistoryContinuation({
      targetMessageId: "agent-1",
      messages: [createMessage("agent-2", "done")],
    });

    expect(event).toBeNull();
  });

  it.each([["done" as const], ["interrupted" as const], ["error" as const]])(
    "returns a persisted-history event for %s target messages",
    (status) => {
      const message = createMessage("agent-1", status);
      const event = resolvePersistedHistoryContinuation({
        targetMessageId: "agent-1",
        messages: [message],
      });

      expect(event).toEqual({
        source: "persisted-history",
        status,
        message,
      });
    },
  );
});
