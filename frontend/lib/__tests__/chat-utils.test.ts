import {
  buildPersistedSessions,
  buildInvokePayload,
  buildSessionCleanupPlan,
  createAgentSession,
  mergeExternalSessionRef,
  sortSessionsByLastActive,
} from "@/lib/chat-utils";

describe("chat store utils", () => {
  it("creates default serializable session state", () => {
    const session = createAgentSession("agent-1");
    expect(session.agentId).toBe("agent-1");
    expect(session.contextId).toBeNull();
    expect(session.streamState).toBe("idle");
    expect(session.transport).toBe("http_json");
    expect(session.inputModes).toEqual(["text/plain"]);
    expect(session.outputModes).toEqual(["text/plain"]);
  });

  it("merges external session refs with fallback semantics", () => {
    const next = mergeExternalSessionRef(
      {
        provider: "opencode",
        externalSessionId: "ext-1",
      },
      {
        externalSessionId: "ext-2",
      },
    );

    expect(next).toEqual({
      provider: "opencode",
      externalSessionId: "ext-2",
    });
  });

  it("builds invoke payload with optional fields", () => {
    const session = createAgentSession("agent-2");
    session.contextId = "ctx-2";
    session.metadata = { locale: "zh-CN" };

    expect(
      buildInvokePayload("hello", session, "session-1", {
        userMessageId: "user-msg-1",
        clientAgentMessageId: "agent-msg-1",
      }),
    ).toEqual({
      query: "hello",
      conversationId: "session-1",
      contextId: "ctx-2",
      userMessageId: "user-msg-1",
      clientAgentMessageId: "agent-msg-1",
      metadata: { locale: "zh-CN" },
    });
  });

  it("always injects opencode_session_id for opencode-bound sessions", () => {
    const session = createAgentSession("agent-3");
    session.metadata = { locale: "zh-CN" };
    session.externalSessionRef = {
      provider: "opencode",
      externalSessionId: "ses-upstream-1",
    };

    expect(buildInvokePayload("hello", session, "conversation:abc")).toEqual({
      query: "hello",
      conversationId: "conversation:abc",
      metadata: {
        locale: "zh-CN",
        opencode_session_id: "ses-upstream-1",
      },
    });
  });

  it("sorts sessions by last active timestamp descending", () => {
    const s1 = createAgentSession("agent-1");
    s1.lastActiveAt = "2026-02-14T12:00:00.000Z";
    const s2 = createAgentSession("agent-1");
    s2.lastActiveAt = "2026-02-14T11:00:00.000Z";

    const sorted = sortSessionsByLastActive([
      ["s2", s2],
      ["s1", s1],
    ]);
    expect(sorted.map(([id]) => id)).toEqual(["s1", "s2"]);
  });

  it("builds cleanup plan for expired and orphaned sessions", () => {
    const active = createAgentSession("agent-1");
    active.lastActiveAt = "2026-02-14T12:00:00.000Z";
    const expired = createAgentSession("agent-2");
    expired.lastActiveAt = "2026-01-01T00:00:00.000Z";

    const plan = buildSessionCleanupPlan(
      {
        active,
        expired,
      },
      ["active", "expired", "orphan-only"],
      new Date("2026-02-14T12:00:00.000Z"),
    );

    expect(plan.changed).toBe(true);
    expect(Object.keys(plan.sessions)).toEqual(["active"]);
    expect(plan.expiredConversationIds).toEqual(["expired"]);
    expect(plan.trimmedConversationIds).toEqual([]);
    expect(plan.orphanedMessageConversationIds).toEqual([
      "expired",
      "orphan-only",
    ]);
  });

  it("trims oldest sessions when active session cap is reached", () => {
    const newest = createAgentSession("agent-1");
    newest.lastActiveAt = "2026-02-14T12:00:00.000Z";
    const middle = createAgentSession("agent-2");
    middle.lastActiveAt = "2026-02-14T11:00:00.000Z";
    const oldest = createAgentSession("agent-3");
    oldest.lastActiveAt = "2026-02-14T10:00:00.000Z";

    const plan = buildSessionCleanupPlan(
      { newest, middle, oldest },
      [],
      new Date("2026-02-14T12:00:00.000Z"),
      2,
    );

    expect(Object.keys(plan.sessions).sort()).toEqual(["middle", "newest"]);
    expect(plan.trimmedConversationIds).toEqual(["oldest"]);
  });

  it("builds bounded persisted sessions and resets volatile fields", () => {
    const newest = createAgentSession("agent-1");
    newest.lastActiveAt = "2026-02-14T12:00:00.000Z";
    newest.streamState = "streaming";
    newest.lastStreamError = "temporary";
    newest.runtimeStatus = "working";

    const older = createAgentSession("agent-2");
    older.lastActiveAt = "2026-02-14T11:00:00.000Z";

    const persisted = buildPersistedSessions({ newest, older }, 1);

    expect(Object.keys(persisted)).toEqual(["newest"]);
    expect(persisted.newest.streamState).toBe("idle");
    expect(persisted.newest.lastStreamError).toBeNull();
    expect(persisted.newest.runtimeStatus).toBeNull();
    expect(persisted.newest.transport).toBe("http_json");
  });
});
