import { render } from "@testing-library/react-native";
import { act } from "react-test-renderer";

import { AuthBootstrap } from "@/components/auth/AuthBootstrap";
import { useSessionStore } from "@/store/session";

const mockEnsureFreshAccessToken = jest.fn(
  async (_options?: { expectedAuthVersion?: number }) => null,
);
const mockRefreshAccessToken = jest.fn(
  async (_options?: { force?: boolean; expectedAuthVersion?: number }) => null,
);
const mockComputeProactiveRefreshLeadMs = jest.fn(
  (_ttlSeconds: number | null) => 5_000,
);
const mockHasExceededAuthRecoveryLimits = jest.fn(() => false);
const mockHandleAuthExpiredOnce = jest.fn();

jest.mock("@/lib/api/client", () => {
  class MockApiConfigError extends Error {
    constructor(message: string) {
      super(message);
      this.name = "ApiConfigError";
    }
  }

  class MockAuthRecoverableError extends Error {
    errorCode = "auth_recovering";

    constructor(message = "Authentication recovery in progress.") {
      super(message);
      this.name = "AuthRecoverableError";
    }
  }

  return {
    ApiConfigError: MockApiConfigError,
    AuthRecoverableError: MockAuthRecoverableError,
    computeProactiveRefreshLeadMs: (ttlSeconds: number | null) =>
      mockComputeProactiveRefreshLeadMs(ttlSeconds),
    hasExceededAuthRecoveryLimits: () => mockHasExceededAuthRecoveryLimits(),
    handleAuthExpiredOnce: () => mockHandleAuthExpiredOnce(),
    ensureFreshAccessToken: (options?: { expectedAuthVersion?: number }) =>
      mockEnsureFreshAccessToken(options),
    refreshAccessToken: (options?: {
      force?: boolean;
      expectedAuthVersion?: number;
    }) => mockRefreshAccessToken(options),
  };
});

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  const AppState = {
    addEventListener: jest.fn(() => ({
      remove: jest.fn(),
    })),
  };
  return new Proxy(actual, {
    get(target, prop, receiver) {
      if (prop === "AppState") {
        return AppState;
      }
      return Reflect.get(target, prop, receiver);
    },
  });
});

describe("AuthBootstrap", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-03-17T12:00:00.000Z"));
    jest.clearAllMocks();
    useSessionStore.setState({
      token: null,
      user: null,
      accessTokenExpiresAtMs: null,
      accessTokenTtlSeconds: null,
      authStatus: "expired",
      recoveryStartedAtMs: null,
      recoveryRetryCount: 0,
      authVersion: 0,
      hydrated: true,
    });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("schedules proactive refresh before token expiry", () => {
    useSessionStore.setState({
      token: "token-1",
      accessTokenExpiresAtMs: Date.now() + 60_000,
      accessTokenTtlSeconds: 30,
      authStatus: "authenticated",
      hydrated: true,
    });

    render(<AuthBootstrap />);

    act(() => {
      jest.advanceTimersByTime(54_999);
    });
    expect(mockEnsureFreshAccessToken).not.toHaveBeenCalled();

    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(mockComputeProactiveRefreshLeadMs).toHaveBeenCalledWith(30);
    expect(mockEnsureFreshAccessToken).toHaveBeenCalledTimes(1);
  });

  it("retries on a short timer while auth is recovering", () => {
    useSessionStore.setState({
      token: "token-1",
      accessTokenExpiresAtMs: Date.now() + 60_000,
      accessTokenTtlSeconds: 30,
      authStatus: "recovering",
      recoveryStartedAtMs: Date.now(),
      recoveryRetryCount: 1,
      hydrated: true,
    });

    render(<AuthBootstrap />);

    act(() => {
      jest.advanceTimersByTime(4_999);
    });
    expect(mockEnsureFreshAccessToken).not.toHaveBeenCalled();

    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(mockEnsureFreshAccessToken).toHaveBeenCalledTimes(1);
  });

  it("forces logout instead of scheduling another retry when recovery window is exceeded", () => {
    mockHasExceededAuthRecoveryLimits.mockReturnValueOnce(true);
    useSessionStore.setState({
      token: "token-1",
      accessTokenExpiresAtMs: Date.now() + 60_000,
      accessTokenTtlSeconds: 30,
      authStatus: "recovering",
      recoveryStartedAtMs: Date.now() - 120_000,
      recoveryRetryCount: 12,
      hydrated: true,
    });

    render(<AuthBootstrap />);

    expect(mockHandleAuthExpiredOnce).toHaveBeenCalledTimes(1);
    expect(mockEnsureFreshAccessToken).not.toHaveBeenCalled();
  });
});
