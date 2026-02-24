import {
  A2AExtensionCallError,
  assertExtensionSuccess,
} from "@/lib/api/a2aExtensions";

jest.mock("@/lib/api/client", () => ({
  apiRequest: jest.fn(),
}));

describe("assertExtensionSuccess", () => {
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
});
