import { type SessionListItem } from "@/lib/api/sessions";
import { resolveSessionAgentPresentation } from "@/lib/sessionDirectoryPresentation";

const createSession = (partial: Partial<SessionListItem>): SessionListItem =>
  ({
    conversationId: "conversation-1",
    source: "manual",
    title: "hello",
    ...partial,
  }) as SessionListItem;

describe("sessionDirectoryPresentation", () => {
  it("uses catalog agent name when available", () => {
    const lookup = new Map([
      [
        "agent-1",
        {
          name: "Planning Agent",
          source: "shared" as const,
        },
      ],
    ]);
    const result = resolveSessionAgentPresentation(
      createSession({ agent_id: "agent-1", agent_source: "personal" }),
      lookup,
    );
    expect(result).toEqual({
      name: "Planning Agent",
      tone: "shared",
    });
  });

  it("falls back to agent id with source tone when catalog is missing", () => {
    const result = resolveSessionAgentPresentation(
      createSession({ agent_id: "agent-2", agent_source: "personal" }),
      new Map(),
    );
    expect(result).toEqual({
      name: "agent-2",
      tone: "personal",
    });
  });

  it("returns unknown when no agent binding is present", () => {
    const result = resolveSessionAgentPresentation(
      createSession({ agent_id: null }),
      new Map(),
    );
    expect(result).toEqual({
      name: "Unknown Agent",
      tone: "unknown",
    });
  });
});
