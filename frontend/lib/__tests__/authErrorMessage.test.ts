import { getFriendlyAuthErrorMessage } from "@/lib/authErrorMessage";

const createApiLikeError = (message: string, status: number) =>
  Object.assign(new Error(message), { status });

describe("getFriendlyAuthErrorMessage", () => {
  it("maps validation payload for email to a friendly message", () => {
    const raw = JSON.stringify({
      message: "Validation error",
      errors: [
        {
          type: "value_error",
          loc: ["body", "email"],
          msg: "value is not a valid email address",
        },
      ],
    });
    const error = createApiLikeError(raw, 422);
    expect(getFriendlyAuthErrorMessage(error)).toBe(
      "Please enter a valid email address.",
    );
  });

  it("falls back to payload message for non-validation errors", () => {
    const raw = JSON.stringify({
      message: "Invalid credentials",
    });
    const error = createApiLikeError(raw, 401);
    expect(getFriendlyAuthErrorMessage(error)).toBe("Invalid credentials");
  });

  it("returns fallback message for validation payload without details", () => {
    const error = createApiLikeError('{"message":"Validation error"}', 422);
    expect(getFriendlyAuthErrorMessage(error)).toBe(
      "Please check your input and try again.",
    );
  });

  it("returns plain text message when not json", () => {
    const error = createApiLikeError("Network busy", 503);
    expect(getFriendlyAuthErrorMessage(error)).toBe("Network busy");
  });
});
