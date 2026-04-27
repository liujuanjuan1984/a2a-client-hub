import {
  A2AExtensionCallError,
  assertExtensionSuccess,
  getExtensionCapabilities,
  listModelProviders,
  listModels,
  promptSessionAsync,
  recoverInterrupts,
  replyElicitationInterrupt,
  replyPermissionInterrupt,
  replyPermissionsInterrupt,
} from "@/lib/api/a2aExtensions";
import { apiRequest } from "@/lib/api/client";

jest.mock("@/lib/api/client", () => ({
  apiRequest: jest.fn(),
}));

const mockedApiRequest = apiRequest as jest.MockedFunction<typeof apiRequest>;

describe("assertExtensionSuccess", () => {
  beforeEach(() => {
    mockedApiRequest.mockReset();
  });

  it("returns for successful responses", () => {
    expect(() => assertExtensionSuccess({ success: true })).not.toThrow();
  });

  it("maps session_forbidden to a semantic message", () => {
    try {
      assertExtensionSuccess({
        success: false,
        error_code: "session_forbidden",
        upstream_error: { message: "forbidden" },
      });
      fail("Expected A2AExtensionCallError");
    } catch (error) {
      expect(error).toBeInstanceOf(A2AExtensionCallError);
      const typed = error as A2AExtensionCallError;
      expect(typed.message).toBe("Session access denied for this operation.");
      expect(typed.errorCode).toBe("session_forbidden");
    }
  });

  it("keeps generic message for other error codes", () => {
    try {
      assertExtensionSuccess({
        success: false,
        error_code: "invalid_params",
        source: "upstream_a2a",
        jsonrpc_code: -32602,
        missing_params: [{ name: "project_id", required: true }],
        upstream_error: { message: "project_id required" },
      });
      fail("Expected A2AExtensionCallError");
    } catch (error) {
      expect(error).toBeInstanceOf(A2AExtensionCallError);
      const typed = error as A2AExtensionCallError;
      expect(typed.message).toBe("Extension call failed (invalid_params)");
      expect(typed.errorCode).toBe("invalid_params");
      expect(typed.source).toBe("upstream_a2a");
      expect(typed.jsonrpcCode).toBe(-32602);
      expect(typed.missingParams).toEqual([
        { name: "project_id", required: true },
      ]);
    }
  });

  it("calls prompt_async endpoint and returns ack result", async () => {
    mockedApiRequest.mockResolvedValue({
      success: true,
      result: { ok: true, session_id: "ses-1" },
    });

    const result = await promptSessionAsync({
      source: "personal",
      agentId: "agent-1",
      sessionId: "ses-1",
      request: {
        parts: [{ type: "text", text: "Continue" }],
      },
      metadata: { provider: "opencode", externalSessionId: "ses-1" },
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/a2a/agents/agent-1/extensions/sessions/ses-1:prompt-async",
      {
        method: "POST",
        body: {
          request: {
            parts: [{ type: "text", text: "Continue" }],
          },
          metadata: {
            shared: {
              session: {
                id: "ses-1",
                provider: "opencode",
              },
            },
          },
        },
      },
    );
    expect(result).toEqual({ ok: true, sessionId: "ses-1" });
  });

  it("throws when prompt_async response does not contain ok=true", async () => {
    mockedApiRequest.mockResolvedValue({
      success: true,
      result: { ok: false },
    });

    await expect(
      promptSessionAsync({
        source: "shared",
        agentId: "agent-1",
        sessionId: "ses-1",
        request: {
          parts: [{ type: "text", text: "Continue" }],
        },
      }),
    ).rejects.toThrow("prompt_async acknowledged without ok=true");
  });

  it("forwards interrupt metadata when provided", async () => {
    mockedApiRequest.mockResolvedValue({
      success: true,
      result: { ok: true, request_id: "perm-1" },
    });

    const result = await replyPermissionInterrupt({
      source: "shared",
      agentId: "agent-1",
      requestId: "perm-1",
      reply: "once",
      metadata: { provider: "opencode", requestScope: "shared" },
      workingDirectory: "/workspace/project",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/a2a/agents/agent-1/extensions/interrupts/permission:reply",
      {
        method: "POST",
        body: {
          request_id: "perm-1",
          reply: "once",
          metadata: { provider: "opencode", requestScope: "shared" },
          workingDirectory: "/workspace/project",
        },
      },
    );
    expect(result).toEqual({ ok: true, requestId: "perm-1" });
  });

  it("calls shared permissions reply endpoint and returns ack", async () => {
    mockedApiRequest.mockResolvedValue({
      success: true,
      result: { ok: true, request_id: "perms-1" },
    });

    const result = await replyPermissionsInterrupt({
      source: "shared",
      agentId: "agent-1",
      requestId: "perms-1",
      permissions: { fileSystem: { write: ["/workspace/project"] } },
      scope: "session",
      metadata: { provider: "opencode" },
      workingDirectory: "/workspace/project",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/a2a/agents/agent-1/extensions/interrupts/permissions:reply",
      {
        method: "POST",
        body: {
          request_id: "perms-1",
          permissions: {
            fileSystem: { write: ["/workspace/project"] },
          },
          scope: "session",
          metadata: { provider: "opencode" },
          workingDirectory: "/workspace/project",
        },
      },
    );
    expect(result).toEqual({ ok: true, requestId: "perms-1" });
  });

  it("calls personal elicitation reply endpoint and returns ack", async () => {
    mockedApiRequest.mockResolvedValue({
      success: true,
      result: { ok: true, request_id: "eli-1" },
    });

    const result = await replyElicitationInterrupt({
      source: "personal",
      agentId: "agent-1",
      requestId: "eli-1",
      action: "accept",
      content: { folder: "docs" },
      metadata: { provider: "opencode" },
      workingDirectory: "/workspace/project",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/a2a/agents/agent-1/extensions/interrupts/elicitation:reply",
      {
        method: "POST",
        body: {
          request_id: "eli-1",
          action: "accept",
          content: { folder: "docs" },
          metadata: { provider: "opencode" },
          workingDirectory: "/workspace/project",
        },
      },
    );
    expect(result).toEqual({ ok: true, requestId: "eli-1" });
  });

  it("calls provider discovery endpoint and normalizes response", async () => {
    mockedApiRequest.mockResolvedValue({
      success: true,
      result: {
        items: [
          {
            provider_id: "openai",
            name: "OpenAI",
            default_model_id: "gpt-5",
          },
        ],
        default_by_provider: { openai: "gpt-5" },
        connected: ["openai"],
      },
    });

    const result = await listModelProviders({
      source: "shared",
      agentId: "agent-1",
      workingDirectory: "/workspace",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/a2a/agents/agent-1/extensions/models/providers:list",
      {
        method: "POST",
        body: {
          workingDirectory: "/workspace",
        },
      },
    );
    expect(result.items[0]?.provider_id).toBe("openai");
    expect(result.defaultByProvider).toEqual({ openai: "gpt-5" });
    expect(result.connected).toEqual(["openai"]);
  });

  it("calls generic extension capabilities endpoint and returns support flags", async () => {
    mockedApiRequest.mockResolvedValue({
      modelSelection: false,
      providerDiscovery: true,
      interruptRecovery: true,
      sessionPromptAsync: true,
      sessionControl: {
        append: {
          declared: true,
          consumedByHub: true,
          status: "supported",
          routeMode: "hybrid",
          requiresStreamIdentity: false,
        },
        promptAsync: {
          declared: true,
          consumedByHub: true,
          availability: "always",
          method: "shared.sessions.prompt_async",
        },
        command: {
          declared: true,
          consumedByHub: true,
          availability: "always",
          method: "shared.sessions.command",
        },
        shell: {
          declared: false,
          consumedByHub: false,
          availability: "conditional",
          configKey: "A2A_ENABLE_SESSION_SHELL",
          enabledByDefault: false,
        },
      },
      invokeMetadata: {
        declared: true,
        consumedByHub: true,
        metadataField: "metadata.shared.invoke",
        appliesToMethods: ["message/send", "message/stream"],
        fields: [
          {
            name: "project_id",
            required: true,
            description: "Project scope.",
          },
          {
            name: "channel_id",
            required: true,
            description: "Channel scope.",
          },
        ],
      },
      runtimeStatus: {
        version: "v1",
        canonicalStates: [
          "working",
          "input-required",
          "auth-required",
          "completed",
          "failed",
          "cancelled",
        ],
        terminalStates: [
          "input-required",
          "auth-required",
          "completed",
          "failed",
          "cancelled",
        ],
        finalStates: ["completed", "failed", "cancelled"],
        interactiveStates: ["input-required", "auth-required"],
        failureStates: ["failed", "cancelled"],
        aliases: {
          input_required: "input-required",
          auth_required: "auth-required",
          canceled: "cancelled",
        },
        passthroughUnknown: true,
      },
    });

    const result = await getExtensionCapabilities({
      source: "shared",
      agentId: "agent-1",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/a2a/agents/agent-1/extensions/capabilities",
      {
        method: "GET",
      },
    );
    expect(result.modelSelection).toBe(false);
    expect(result.providerDiscovery).toBe(true);
    expect(result.interruptRecovery).toBe(true);
    expect(result.sessionPromptAsync).toBe(true);
    expect(result.sessionControl.append.status).toBe("supported");
    expect(result.sessionControl.append.routeMode).toBe("hybrid");
    expect(result.sessionControl.command.consumedByHub).toBe(true);
    expect(result.sessionControl.shell.availability).toBe("conditional");
    expect(result.invokeMetadata.metadataField).toBe("metadata.shared.invoke");
    expect(result.invokeMetadata.fields[0]?.name).toBe("project_id");
    expect(result.runtimeStatus.version).toBe("v1");
    expect(result.runtimeStatus.aliases.canceled).toBe("cancelled");
  });

  it("calls model discovery endpoint with provider filter", async () => {
    mockedApiRequest.mockResolvedValue({
      success: true,
      result: {
        items: [
          {
            provider_id: "openai",
            model_id: "gpt-5",
            name: "GPT-5",
          },
        ],
        default_by_provider: { openai: "gpt-5" },
        connected: ["openai"],
      },
    });

    const result = await listModels({
      source: "personal",
      agentId: "agent-1",
      providerId: "openai",
      workingDirectory: "/workspace",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/a2a/agents/agent-1/extensions/models:list",
      {
        method: "POST",
        body: {
          provider_id: "openai",
          workingDirectory: "/workspace",
        },
      },
    );
    expect(result.items[0]?.model_id).toBe("gpt-5");
  });

  it("calls interrupt recovery endpoint and maps pending interrupts", async () => {
    mockedApiRequest.mockResolvedValue({
      items: [
        {
          requestId: "perm-1",
          sessionId: "sess-1",
          type: "permission",
          details: {
            permission: "write",
            patterns: ["src/**"],
            displayMessage: "Approve write access",
          },
          expiresAt: 120,
          source: "recovery",
        },
        {
          requestId: "q-1",
          sessionId: "sess-1",
          type: "question",
          details: {
            displayMessage: "Need an answer",
            questions: [
              {
                header: "Scope",
                question: "Which files?",
                options: [{ label: "All", description: null, value: "all" }],
              },
            ],
          },
          source: "recovery",
        },
        {
          requestId: "perms-1",
          sessionId: "sess-1",
          type: "permissions",
          details: {
            displayMessage: "Approve workspace access",
            permissions: {
              fileSystem: { write: ["/workspace/project"] },
            },
          },
          source: "recovery",
        },
        {
          requestId: "eli-1",
          sessionId: "sess-1",
          type: "elicitation",
          details: {
            display_message: "Select the target folder",
            mode: "form",
            server_name: "workspace-server",
            requested_schema: {
              type: "object",
              properties: { folder: { type: "string" } },
            },
            url: "https://example.com/form",
            elicitation_id: "elicitation-1",
          },
          source: "recovery",
        },
      ],
    });

    const result = await recoverInterrupts({
      source: "shared",
      agentId: "agent-1",
      sessionId: "sess-1",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/a2a/agents/agent-1/extensions/interrupts:recover",
      {
        method: "POST",
        body: { sessionId: "sess-1" },
      },
    );
    expect(result.items).toEqual([
      {
        requestId: "perm-1",
        sessionId: "sess-1",
        type: "permission",
        phase: "asked",
        source: "recovery",
        taskId: null,
        contextId: null,
        expiresAt: 120,
        details: {
          permission: "write",
          patterns: ["src/**"],
          displayMessage: "Approve write access",
        },
      },
      {
        requestId: "q-1",
        sessionId: "sess-1",
        type: "question",
        phase: "asked",
        source: "recovery",
        taskId: null,
        contextId: null,
        expiresAt: null,
        details: {
          displayMessage: "Need an answer",
          questions: [
            {
              header: "Scope",
              description: null,
              question: "Which files?",
              options: [{ label: "All", description: null, value: "all" }],
            },
          ],
        },
      },
      {
        requestId: "perms-1",
        sessionId: "sess-1",
        type: "permissions",
        phase: "asked",
        source: "recovery",
        taskId: null,
        contextId: null,
        expiresAt: null,
        details: {
          displayMessage: "Approve workspace access",
          permissions: {
            fileSystem: { write: ["/workspace/project"] },
          },
        },
      },
      {
        requestId: "eli-1",
        sessionId: "sess-1",
        type: "elicitation",
        phase: "asked",
        source: "recovery",
        taskId: null,
        contextId: null,
        expiresAt: null,
        details: {
          displayMessage: "Select the target folder",
          mode: "form",
          serverName: "workspace-server",
          requestedSchema: {
            type: "object",
            properties: { folder: { type: "string" } },
          },
          url: "https://example.com/form",
          elicitationId: "elicitation-1",
        },
      },
    ]);
  });
});
