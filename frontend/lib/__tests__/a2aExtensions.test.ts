import {
  A2AExtensionCallError,
  assertExtensionSuccess,
  promptOpencodeSessionAsync,
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

    const result = await promptOpencodeSessionAsync({
      source: "personal",
      agentId: "agent-1",
      sessionId: "ses-1",
      request: {
        parts: [{ type: "text", text: "Continue" }],
      },
      metadata: { opencode: { directory: "/workspace/project" } },
    });

    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/a2a/agents/agent-1/extensions/opencode/sessions/ses-1:prompt-async",
      {
        method: "POST",
        body: {
          request: {
            parts: [{ type: "text", text: "Continue" }],
          },
          metadata: { opencode: { directory: "/workspace/project" } },
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
      promptOpencodeSessionAsync({
        source: "shared",
        agentId: "agent-1",
        sessionId: "ses-1",
        request: {
          parts: [{ type: "text", text: "Continue" }],
        },
      }),
    ).rejects.toThrow("prompt_async acknowledged without ok=true");
  });
});
