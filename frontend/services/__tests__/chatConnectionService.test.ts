jest.mock("@/lib/api/client", () => {
  class MockApiRequestError extends Error {
    status: number;
    errorCode: string | null;

    constructor(
      message: string,
      status: number,
      errorCode: string | null = null,
    ) {
      super(message);
      this.name = "ApiRequestError";
      this.status = status;
      this.errorCode = errorCode;
    }
  }

  return {
    ApiRequestError: MockApiRequestError,
    isAuthFailureError: jest.fn(() => false),
    isAuthorizationFailureError: jest.fn(() => false),
  };
});

jest.mock("@/lib/api/sessions", () => ({
  cancelSession: jest.fn(),
}));

const { ApiRequestError } = require("@/lib/api/client") as {
  ApiRequestError: new (
    message: string,
    status: number,
    errorCode?: string | null,
  ) => Error;
};
const { cancelSession: cancelSessionApi } = require("@/lib/api/sessions") as {
  cancelSession: jest.Mock;
};
const { chatConnectionService } =
  require("@/services/chatConnectionService") as {
    chatConnectionService: {
      cancelSession: (conversationId: string) => Promise<unknown>;
    };
  };

describe("chatConnectionService.cancelSession", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("treats session_not_found as an idempotent no-op", async () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    cancelSessionApi.mockRejectedValue(
      new ApiRequestError('{"message":"session_not_found"}', 404),
    );

    const result = await chatConnectionService.cancelSession(" conv-1 ");

    expect(result).toEqual({
      conversationId: "conv-1",
      taskId: null,
      cancelled: false,
      status: "no_inflight",
    });
    expect(warnSpy).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("logs warning for non-idempotent cancellation failures", async () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    cancelSessionApi.mockRejectedValue(new ApiRequestError("boom", 500));

    const result = await chatConnectionService.cancelSession("conv-2");

    expect(result).toBeNull();
    expect(warnSpy).toHaveBeenCalledTimes(1);
    warnSpy.mockRestore();
  });
});
