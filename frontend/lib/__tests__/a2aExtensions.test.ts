import {
  A2AExtensionCallError,
  assertExtensionSuccess,
  getExtensionCapabilities,
  listModelProviders,
  listModels,
  promptSessionAsync,
  replyPermissionInterrupt,
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
        error_code: "upstream_error",
      });
      fail("Expected A2AExtensionCallError");
    } catch (error) {
      expect(error).toBeInstanceOf(A2AExtensionCallError);
      const typed = error as A2AExtensionCallError;
      expect(typed.message).toBe("Extension call failed (upstream_error)");
      expect(typed.errorCode).toBe("upstream_error");
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
          metadata: { provider: "opencode", externalSessionId: "ses-1" },
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
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/a2a/agents/agent-1/extensions/interrupts/permission:reply",
      {
        method: "POST",
        body: {
          request_id: "perm-1",
          reply: "once",
          metadata: { provider: "opencode", requestScope: "shared" },
        },
      },
    );
    expect(result).toEqual({ ok: true, requestId: "perm-1" });
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
      sessionMetadata: {
        shared: { model: { providerID: "openai", modelID: "gpt-5" } },
        opencode: { directory: "/workspace" },
      },
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/a2a/agents/agent-1/extensions/models/providers:list",
      {
        method: "POST",
        body: {
          session_metadata: {
            shared: { model: { providerID: "openai", modelID: "gpt-5" } },
            opencode: { directory: "/workspace" },
          },
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
    expect(result).toEqual({ modelSelection: false });
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
      sessionMetadata: {
        shared: { model: { providerID: "openai", modelID: "gpt-5" } },
        opencode: { directory: "/workspace" },
      },
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/a2a/agents/agent-1/extensions/models:list",
      {
        method: "POST",
        body: {
          provider_id: "openai",
          session_metadata: {
            shared: { model: { providerID: "openai", modelID: "gpt-5" } },
            opencode: { directory: "/workspace" },
          },
        },
      },
    );
    expect(result.items[0]?.model_id).toBe("gpt-5");
  });
});
