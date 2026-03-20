import {
  buildPersistedSessions,
  buildInvokePayload,
  buildSessionCleanupPlan,
  createAgentSession,
  getSharedModelSelection,
  mergeExternalSessionRef,
  sortSessionsByLastActive,
  withSharedModelSelection,
} from "@/lib/chat-utils";

describe("chat store utils", () => {
  it("creates default serializable session state", () => {
    const session = createAgentSession("agent-1");
    expect(session.agentId).toBe("agent-1");
    expect(session.contextId).toBeNull();
    expect(session.streamState).toBe("idle");
    expect(session.pendingInterrupt).toBeNull();
    expect(session.lastResolvedInterrupt).toBeNull();
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
      externalSessionId: "ext-1",
    });
  });

  it("falls back to incoming external session id when existing is empty", () => {
    const next = mergeExternalSessionRef(
      {
        provider: null,
        externalSessionId: null,
      },
      {
        provider: "opencode",
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
        agentMessageId: "agent-msg-1",
      }),
    ).toEqual({
      query: "hello",
      conversationId: "session-1",
      contextId: "ctx-2",
      userMessageId: "user-msg-1",
      agentMessageId: "agent-msg-1",
      metadata: { locale: "zh-CN" },
    });
  });

  it("builds neutral session binding intent for bound sessions", () => {
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
      },
      sessionBinding: {
        provider: "opencode",
        externalSessionId: "ses-upstream-1",
      },
    });
  });

  it("strips binding-shaped metadata and only keeps neutral session binding intent", () => {
    const session = createAgentSession("agent-3");
    session.metadata = {
      locale: "zh-CN",
      provider: "legacy",
      externalSessionId: "legacy-sid",
      shared: {
        session: {
          id: "legacy-sid",
          provider: "legacy",
        },
      },
    };
    session.externalSessionRef = {
      provider: "OpenCode",
      externalSessionId: "ses-upstream-2",
    };

    expect(buildInvokePayload("hello", session, "conversation:def")).toEqual({
      query: "hello",
      conversationId: "conversation:def",
      metadata: {
        locale: "zh-CN",
      },
      sessionBinding: {
        provider: "opencode",
        externalSessionId: "ses-upstream-2",
      },
    });
  });

  it("reads and writes shared model selection metadata", () => {
    const nextMetadata = withSharedModelSelection(
      { locale: "zh-CN" },
      {
        providerID: "openai",
        modelID: "gpt-5",
      },
    );

    expect(getSharedModelSelection(nextMetadata)).toEqual({
      providerID: "openai",
      modelID: "gpt-5",
    });
    expect(withSharedModelSelection(nextMetadata, null)).toEqual({
      locale: "zh-CN",
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
    newest.source = "manual";
    newest.contextId = "ctx-1";
    newest.metadata = {
      locale: "zh-CN",
      opencode: {
        directory: "/workspace/app",
      },
      shared: {
        model: {
          providerID: "openai",
          modelID: "gpt-5",
        },
        session: {
          provider: "opencode",
          id: "upstream-session-1",
        },
      },
    };
    newest.externalSessionRef = {
      provider: "opencode",
      externalSessionId: "ses-upstream-1",
    };
    newest.streamState = "streaming";
    newest.lastStreamError = "temporary";
    newest.runtimeStatus = "working";
    newest.lastReceivedSequence = 42;
    newest.lastUserMessageId = "user-1";
    newest.lastAgentMessageId = "agent-1";
    newest.pendingInterrupt = {
      requestId: "perm-1",
      type: "permission",
      phase: "asked",
      details: { permission: "read", patterns: ["/repo/.env"] },
    };
    newest.lastResolvedInterrupt = {
      requestId: "q-1",
      type: "question",
      phase: "resolved",
      resolution: "replied",
      observedAt: "2026-02-14T12:00:05.000Z",
    };

    const older = createAgentSession("agent-2");
    older.lastActiveAt = "2026-02-14T11:00:00.000Z";

    const persisted = buildPersistedSessions({ newest, older }, 1);

    expect(Object.keys(persisted)).toEqual(["newest"]);
    expect(persisted.newest.streamState).toBe("idle");
    expect(persisted.newest.lastStreamError).toBeNull();
    expect(persisted.newest.runtimeStatus).toBeNull();
    expect(persisted.newest.pendingInterrupt).toBeNull();
    expect(persisted.newest.lastResolvedInterrupt).toBeNull();
    expect(persisted.newest.transport).toBe("http_json");
    expect(persisted.newest.source).toBeNull();
    expect(persisted.newest.contextId).toBeNull();
    expect(persisted.newest.metadata).toEqual({
      opencode: {
        directory: "/workspace/app",
      },
      shared: {
        model: {
          providerID: "openai",
          modelID: "gpt-5",
        },
      },
    });
    expect(persisted.newest.externalSessionRef).toBeNull();
    expect(persisted.newest.lastReceivedSequence).toBeUndefined();
    expect(persisted.newest.lastUserMessageId).toBeUndefined();
    expect(persisted.newest.lastAgentMessageId).toBeUndefined();
  });
});
